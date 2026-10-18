"""Catalog indexing replacement and shared embedding serialization contracts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from serviceBot.api import portal
from serviceBot.services import rag


class CapturedCollection:
    def __init__(self):
        self.entries = {'old-catalog': ('previous catalog', {'filename':'auto_services_catalog.txt'}),
                        'unrelated': ('unrelated retained knowledge', {'filename':'other.txt'})}
        self.fail_add = False

    def get(self, where, include=None):
        return {'ids':[key for key, (_, meta) in self.entries.items() if all(meta.get(k)==v for k,v in where.items())]}

    def add(self, documents, metadatas, ids):
        if self.fail_add:
            raise RuntimeError('captured embedding failure')
        self.entries.update({key:(doc,meta) for key,doc,meta in zip(ids,documents,metadatas)})

    def delete(self, where=None, ids=None):
        if ids is not None:
            self.entries = {k:v for k,v in self.entries.items() if k not in ids}
        else:
            self.entries = {k:v for k,v in self.entries.items() if not all(v[1].get(a)==b for a,b in where.items())}


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    collection = CapturedCollection()
    monkeypatch.setattr(portal, 'KB_DIR', str(tmp_path))
    captured = collection
    def initialize(self, collection=None):
        self.collection = captured if collection is None else collection
    monkeypatch.setattr(rag.FAQService, '__init__', initialize)
    target = tmp_path/'auto_services_catalog.txt'
    target.write_text('previous catalog')
    return collection, target


def test_failed_catalog_embedding_preserves_prior_file_chunks_and_unrelated_document(catalog):
    collection, target = catalog
    before = dict(collection.entries)
    collection.fail_add = True
    with pytest.raises(RuntimeError, match='embedding failure'):
        portal.sync_services_to_kb()
    assert target.read_text() == 'previous catalog'
    assert collection.entries == before
    assert list(target.parent.iterdir()) == [target]


def test_successful_catalog_replacement_deletes_only_exact_prior_ids(catalog):
    collection, target = catalog
    portal.sync_services_to_kb()
    assert 'old-catalog' not in collection.entries
    assert collection.entries['unrelated'] == ('unrelated retained knowledge', {'filename':'other.txt'})
    assert any(meta['filename']=='auto_services_catalog.txt' for _,meta in collection.entries.values())
    assert target.read_text().startswith('# Auto Service Catalog and Offerings')
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize('operation', ['initialization','add','query'])
def test_all_embedding_owners_serialize_against_indexing(monkeypatch, operation):
    first_entered, release_first, second_entered = Event(), Event(), Event()
    collection = CapturedCollection()
    count_lock = Lock()
    calls = 0
    original_add = collection.add
    def add(**kwargs):
        nonlocal calls
        with count_lock:
            calls += 1
            first = calls == 1
        if first:
            first_entered.set()
            assert release_first.wait(5), 'test failed to release captured embedding'
        else:
            second_entered.set()
        original_add(**kwargs)
    collection.add = add
    collection.count = lambda: 1
    def query(**kwargs):
        second_entered.set()
        raise RuntimeError('captured query reached')
    collection.query = query
    first = rag.FAQService(collection=collection)
    if operation == 'initialization':
        def client(**kwargs):
            second_entered.set()
            return SimpleNamespace(get_or_create_collection=lambda *a,**kwargs:collection)
        monkeypatch.setattr(rag.chromadb,'PersistentClient',client)
        second = lambda: rag.FAQService()
    elif operation == 'add':
        second = lambda: rag.FAQService(collection=collection).index_text('second content','second.txt')
    else:
        second = lambda: rag.FAQService(collection=collection).answer_question('catalog?')
    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(first.index_text,'first content','first.txt')
        assert first_entered.wait(2)
        two = executor.submit(second)
        try:
            assert not second_entered.wait(.15), 'embedding owners overlapped'
        finally:
            release_first.set()
        assert one.result(timeout=2) == 1
        if operation == 'query':
            with pytest.raises(RuntimeError,match='captured query reached'): two.result(timeout=2)
        else:
            two.result(timeout=2)
        assert second_entered.is_set()


def test_catalog_snapshot_is_inside_serialized_replacement_boundary(catalog, monkeypatch):
    from serviceBot.db.connection import get_db_connection
    collection, target = catalog
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute("INSERT INTO services(name,duration_minutes) VALUES('Catalog serialized old',30) RETURNING id")
        service_id = cursor.fetchone()[0]
    first_entered, release_first, second_requested, second_added, second_snapshot = Event(), Event(), Event(), Event(), Event()
    from serviceBot.db import connection
    original_cursor = connection.dict_cursor
    snapshots = 0
    @contextmanager
    def observing_cursor(conn):
        nonlocal snapshots
        with original_cursor(conn) as cursor:
            class Cursor:
                def execute(self, statement, *params):
                    nonlocal snapshots
                    if statement.startswith('SELECT name, description, price_range, duration_minutes FROM services'):
                        snapshots += 1
                        if snapshots == 2: second_snapshot.set()
                    return cursor.execute(statement, *params)
                def fetchall(self): return cursor.fetchall()
            yield Cursor()
    monkeypatch.setattr(connection,'dict_cursor',observing_cursor)
    original_add = collection.add
    count = 0
    count_lock = Lock()
    def add(**kwargs):
        nonlocal count
        with count_lock:
            count += 1
            first = count == 1
        if first:
            first_entered.set()
            assert release_first.wait(5)
        else:
            second_added.set()
        original_add(**kwargs)
    collection.add = add
    def second_sync():
        second_requested.set()
        portal.sync_services_to_kb()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(portal.sync_services_to_kb)
            assert first_entered.wait(2)
            with get_db_connection() as conn, conn.cursor() as cursor:
                cursor.execute("UPDATE services SET name='Catalog serialized latest' WHERE id=%s",[service_id])
            second = executor.submit(second_sync)
            assert second_requested.wait(2)
            try:
                assert not second_snapshot.wait(.15), 'catalog snapshot escaped serialization boundary'
                assert not second_added.is_set(), 'catalog embedding operations overlapped'
            finally:
                release_first.set()
            first.result(timeout=3)
            second.result(timeout=3)
        text = target.read_text()
        assert 'Catalog serialized latest' in text and 'Catalog serialized old' not in text
        indexed = ' '.join(doc for doc,meta in collection.entries.values() if meta['filename']=='auto_services_catalog.txt')
        assert 'Catalog serialized latest' in indexed and 'Catalog serialized old' not in indexed
        assert collection.entries['unrelated'][0] == 'unrelated retained knowledge'
    finally:
        release_first.set()
        with get_db_connection() as conn, conn.cursor() as cursor:
            cursor.execute('DELETE FROM services WHERE id=%s',[service_id])


def test_actual_chroma_replacement_retains_unrelated_document_and_new_generation():
    import uuid

    import chromadb

    from tests.test_rag_faq import KeywordMockEmbeddingFunction
    client = chromadb.EphemeralClient()
    collection = client.create_collection('catalog-contract-'+uuid.uuid4().hex, embedding_function=KeywordMockEmbeddingFunction())
    collection.add(documents=['old oil change catalog','unrelated hours'], metadatas=[{'filename':'catalog.txt'},{'filename':'other.txt'}], ids=['old','other'])
    count = rag.FAQService(collection=collection).replace_text('updated oil change catalog','catalog.txt')
    assert count == 1
    snapshot = collection.get()
    assert 'old' not in snapshot['ids'] and 'other' in snapshot['ids']
    assert collection.get(where={'filename':'catalog.txt'})['documents'] == ['updated oil change catalog']


@pytest.mark.parametrize('value,past', [
    ('2026-10-18T15:59:00+00:00',True), ('2026-10-18T16:01:00+00:00',False),
    ('2026-10-18 08:59:00',True), ('2026-10-18 09:01:00',False), ('not parseable',False),
])
def test_past_candidate_guard_uses_configured_business_timezone(monkeypatch,value,past):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from serviceBot.services import timezone_service
    zone = ZoneInfo('America/Los_Angeles')
    monkeypatch.setattr(timezone_service,'get_business_zoneinfo',lambda:zone)
    monkeypatch.setattr(timezone_service,'now_in_business_tz',lambda:datetime(2026,10,18,9,tzinfo=zone))
    assert portal._booking_start_is_past(value) is past


def test_large_index_adds_one_chunk_per_embedding_call():
    collection = CapturedCollection()
    sizes = []
    original = collection.add
    def add(**kwargs):
        sizes.append(len(kwargs['documents']))
        original(**kwargs)
    collection.add = add
    count = rag.FAQService(collection=collection).index_text('bounded embedding content '*500,'large.txt')
    assert count > 10
    assert sizes == [1]*count


@pytest.mark.parametrize('persist_failing_batch', [False,True])
def test_late_batch_failure_rolls_back_exact_attempt_ids_including_current(catalog,persist_failing_batch):
    collection, _target = catalog
    before = dict(collection.entries)
    calls = 0
    attempted = []
    original = collection.add
    def add(**kwargs):
        nonlocal calls
        calls += 1
        attempted.extend(kwargs['ids'])
        if calls == 2:
            if persist_failing_batch: original(**kwargs)
            raise RuntimeError('captured late embedding failure')
        original(**kwargs)
    collection.add = add
    with pytest.raises(RuntimeError,match='late embedding failure'):
        rag.FAQService(collection=collection).replace_text('replacement content '*400,'auto_services_catalog.txt')
    assert len(attempted) == 2
    assert collection.entries == before


def test_attempt_rollback_failure_is_surfaced_not_reported_as_success(catalog):
    collection, _target = catalog
    original = collection.add
    calls = 0
    def add(**kwargs):
        nonlocal calls
        calls += 1
        original(**kwargs)
        if calls == 2: raise RuntimeError('captured indexing failure')
    def failed_cleanup(**kwargs):
        assert kwargs.get('ids')
        raise RuntimeError('captured rollback failed')
    collection.add = add
    collection.delete = failed_cleanup
    with pytest.raises(RuntimeError,match='rollback failed'):
        rag.FAQService(collection=collection).replace_text('replacement content '*400,'auto_services_catalog.txt')
    assert collection.entries['old-catalog'][0] == 'previous catalog'
    assert collection.entries['unrelated'][0] == 'unrelated retained knowledge'


def test_same_filename_upload_holds_lock_through_atomic_file_publication(catalog,monkeypatch):
    collection, target = catalog
    first_publication, release, second_started, second_indexed = Event(), Event(), Event(), Event()
    original_replace = portal.os.replace
    original_add = collection.add
    count = 0
    def replace(source,destination):
        nonlocal count
        count += 1
        if count == 1:
            first_publication.set()
            assert release.wait(5)
        return original_replace(source,destination)
    def add(**kwargs):
        if kwargs['documents'] == ['second']: second_indexed.set()
        original_add(**kwargs)
    monkeypatch.setattr(portal.os,'replace',replace)
    collection.add = add
    def second():
        second_started.set()
        return portal._store_kb_upload('same.txt',b'second','second')
    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(portal._store_kb_upload,'same.txt',b'first','first')
        assert first_publication.wait(2)
        two = executor.submit(second)
        assert second_started.wait(2)
        try:
            assert not second_indexed.wait(.15),'index/file publication interleaved'
        finally:
            release.set()
        assert one.result(timeout=2)['success']
        assert two.result(timeout=2)['success']
    assert (target.parent/'same.txt').read_bytes() == b'second'
    assert [doc for doc,meta in collection.entries.values() if meta['filename']=='same.txt'] == ['second']


def test_real_chroma_bounded_add_and_late_persisted_batch_rollback(monkeypatch):
    import uuid

    import chromadb

    from tests.test_rag_faq import KeywordMockEmbeddingFunction
    class TrackingEmbedding(KeywordMockEmbeddingFunction):
        def __init__(self): self.sizes = []
        def __call__(self,input):
            self.sizes.append(len(input))
            return super().__call__(input)
    embedding = TrackingEmbedding()
    collection = chromadb.EphemeralClient().create_collection('bounded-'+uuid.uuid4().hex,embedding_function=embedding)
    collection.add(documents=['previous catalog','unrelated retained knowledge'],metadatas=[{'filename':'catalog.txt'},{'filename':'other.txt'}],ids=['old','unrelated'])
    embedding.sizes.clear()
    original_add = type(collection).add
    calls = 0
    def late_add(self,*args,**kwargs):
        nonlocal calls
        result = original_add(self,*args,**kwargs)
        if self is collection:
            calls += 1
            if calls == 2: raise RuntimeError('persisted current batch then failed')
        return result
    monkeypatch.setattr(type(collection),'add',late_add)
    with pytest.raises(RuntimeError,match='persisted current batch'):
        rag.FAQService(collection=collection).replace_text('bounded replacement content '*400,'catalog.txt')
    assert embedding.sizes == [1,1]
    assert set(collection.get()['ids']) == {'old','unrelated'}


@pytest.fixture
def captured_default_encoder(monkeypatch):
    from chromadb.utils.embedding_functions import onnx_mini_lm_l6_v2
    instances, calls = [], []
    class Encoder:
        def __init__(self): instances.append(self)
        def __call__(self,input):
            calls.append((self,list(input)))
            return [[float(len(text))]+[0.0]*383 for text in input]
    monkeypatch.setattr(onnx_mini_lm_l6_v2,'ONNXMiniLM_L6_V2',Encoder)
    # Start with the same lazy state as a newly started process.
    monkeypatch.setattr(rag,'_DEFAULT_ENCODER',None,raising=False)
    return instances,calls


def test_default_encoder_is_lazy_and_reused_across_owners_adds_and_query(monkeypatch,captured_default_encoder):
    import uuid

    import chromadb
    client = chromadb.EphemeralClient()
    name = 'default-owner-'+uuid.uuid4().hex
    selected = []
    def collection(collection_name,**kwargs):
        selected.append(kwargs.get('embedding_function'))
        return client.get_or_create_collection(name,**kwargs)
    monkeypatch.setattr(rag.chromadb,'PersistentClient',lambda **kwargs:SimpleNamespace(get_or_create_collection=collection))
    one, two = rag.FAQService(), rag.FAQService()
    instances,calls = captured_default_encoder
    assert instances == []
    one.index_text('first chunk '*150,'first.txt')
    two.index_text('second content','second.txt')
    two.collection.query(query_texts=['first chunk'],n_results=1)
    assert len(instances) == 1
    assert len(calls) > 3 and all(owner is instances[0] for owner,_ in calls)
    assert all(len(texts)==1 for _,texts in calls)
    assert all(function is not None and function.name()=='default' and function.get_config()=={} for function in selected)
    rebuilt = type(selected[0]).build_from_config({})
    rebuilt(['rebuilt owner query'])
    assert type(rebuilt) is type(selected[0])
    assert len(instances) == 1


def test_injected_collection_does_not_initialize_default_encoder(captured_default_encoder):
    collection = CapturedCollection()
    rag.FAQService(collection=collection).index_text('captured injected content','test.txt')
    assert captured_default_encoder == ([],[])


def test_existing_persisted_default_collection_reopens_compatible_without_download(monkeypatch,tmp_path,captured_default_encoder):
    import chromadb
    client = chromadb.PersistentClient(path=str(tmp_path/'default-chroma'))
    original = client.get_or_create_collection('faq_collection')
    original.add(ids=['existing-default-row'],documents=['prior knowledge'],embeddings=[[1.0]+[0.0]*383])
    assert original.configuration['embedding_function'].name() == 'default'
    assert original.configuration['embedding_function'].get_config() == {}
    monkeypatch.setattr(rag.chromadb,'PersistentClient',lambda **kwargs:client)
    service = rag.FAQService()
    assert captured_default_encoder == ([],[])
    assert service.index_text('compatible new knowledge '*100,'new.txt') > 1
    reopened = rag.FAQService()
    result = reopened.collection.query(query_texts=['prior knowledge'],n_results=1)
    assert result['ids'][0]
    snapshot = reopened.collection.get(include=['embeddings'])
    assert 'existing-default-row' in snapshot['ids']
    assert all(len(vector)==384 for vector in snapshot['embeddings'])
    assert reopened.collection.configuration['embedding_function'].name() == 'default'
    assert reopened.collection.configuration['embedding_function'].get_config() == {}
    instances,calls = captured_default_encoder
    assert len(instances)==1
    assert all(instance is instances[0] for instance,_ in calls)
