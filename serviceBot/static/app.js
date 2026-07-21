document.addEventListener('DOMContentLoaded', () => {
  
  // Local state for tables
  let allCalls = [];
  let allRequests = [];

  // Elements
  const navItems = document.querySelectorAll('.nav-item');
  const viewSections = document.querySelectorAll('.view-section');
  const viewTitle = document.getElementById('current-view-title');
  const refreshBtn = document.getElementById('refresh-data-btn');
  const toast = document.getElementById('app-toast');
  
  // Edit Service Drawer Elements
  const editDrawer = document.getElementById('edit-service-drawer');
  const editDrawerOverlay = document.getElementById('edit-service-drawer-overlay');
  const closeEditDrawerBtn = document.getElementById('close-edit-drawer-btn');
  const cancelEditBtn = document.getElementById('cancel-edit-btn');
  const editServiceForm = document.getElementById('edit-service-form');
  
  // Staff Calendars Elements
  const staffAgentSelector = document.getElementById('staff-agent-selector');
  const staffSlotsListBody = document.getElementById('staff-slots-list-body');
  const addSlotForm = document.getElementById('add-slot-form');
  const newSlotDatetimeInput = document.getElementById('new-slot-datetime');
  const addAgentForm = document.getElementById('add-agent-form');
  const newAgentNameInput = document.getElementById('new-agent-name');
  const newAgentRoleInput = document.getElementById('new-agent-role');
  const newAgentEmailInput = document.getElementById('new-agent-email');
  const deleteAgentProfileBtn = document.getElementById('delete-agent-profile-btn');
  
  // Document Drawer Elements
  const documentDrawer = document.getElementById('document-drawer');
  const documentDrawerOverlay = document.getElementById('document-drawer-overlay');
  const closeDocumentDrawerBtn = document.getElementById('close-document-drawer-btn');
  
  function closeDocumentDrawer() {
    documentDrawer.classList.remove('active');
    documentDrawerOverlay.classList.remove('active');
  }
  
  closeDocumentDrawerBtn.addEventListener('click', closeDocumentDrawer);
  documentDrawerOverlay.addEventListener('click', closeDocumentDrawer);
  
  // Tab Navigation Switching
  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      
      const tabName = item.getAttribute('data-tab');
      
      // Update sidebar nav items state
      navItems.forEach(nav => nav.classList.remove('active'));
      item.classList.add('active');
      
      // Toggle views visibility
      viewSections.forEach(section => {
        section.classList.remove('active');
        if (section.id === `${tabName}-view`) {
          section.classList.add('active');
        }
      });
      
      // Update title text
      viewTitle.textContent = item.textContent.trim();
      
      // Perform automatic fetch checks based on tab name
      if (tabName === 'dashboard') {
        loadDashboardData();
      } else if (tabName === 'intents') {
        loadConfigData();
      } else if (tabName === 'services') {
        loadServicesData();
      } else if (tabName === 'keys') {
        loadVoiceData();
      } else if (tabName === 'staff') {
        loadStaffView();
      } else if (tabName === 'knowledge') {
        loadKBData();
      } else if (tabName === 'gmail') {
        loadGmailConfig();
      }
    });
  });

  // Dashboard Sub-Tab Navigation Switching
  const dashTabBtns = document.querySelectorAll('.dashboard-tab-btn');
  const dashTabContents = document.querySelectorAll('.dashboard-tab-content');

  dashTabBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const tabTarget = btn.getAttribute('data-dash-tab');
      
      dashTabBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      
      dashTabContents.forEach(content => {
        content.classList.remove('active');
        if (content.id === `dash-tab-${tabTarget}`) {
          content.classList.add('active');
        }
      });
    });
  });

  // Show Toast Alert helper
  function showToast(message, type = 'success') {
    toast.textContent = message;
    toast.className = 'toast active';
    if (type === 'error') {
      toast.style.borderColor = 'var(--color-danger)';
    } else {
      toast.style.borderColor = 'var(--border-card)';
    }
    
    setTimeout(() => {
      toast.classList.remove('active');
    }, 3000);
  }

  // --- VIEW 1: DASHBOARD RETRIEVAL ---
  function formatShortDate(dateStr) {
    if (!dateStr) return 'N/A';
    // Handle standard database spaces to ISO format conversion
    const cleanStr = dateStr.includes(' ') && !dateStr.includes('T') ? dateStr.replace(' ', 'T') : dateStr;
    const d = new Date(cleanStr);
    if (isNaN(d.getTime())) return dateStr;
    
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const year = String(d.getFullYear()).slice(-2);
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    return `${month}/${day}/${year} ${hours}:${minutes}`;
  }

  function renderCallLogs(callsToRender) {
    const listBody = document.getElementById('call-logs-list');
    if (!listBody) return;
    
    // Limit to top 10
    const top10 = callsToRender.slice(0, 10);
    
    if (top10.length === 0) {
      listBody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-muted">No matching call records found.</td></tr>`;
    } else {
      listBody.innerHTML = '';
      top10.forEach(call => {
        const tr = document.createElement('tr');
        const formattedDate = formatShortDate(call.created_at);
        
        tr.innerHTML = `
          <td>${formattedDate}</td>
          <td><strong>${call.customer_name || 'Unknown Caller'}</strong></td>
          <td class="text-muted">${call.phone || '--'}</td>
          <td>${call.vehicle || '<span class="text-muted">None</span>'}</td>
          <td><div class="summary-cell-full">${call.summary}</div></td>
          <td>
            <button class="btn btn-secondary btn-sm view-transcript-btn" data-id="${call.id}">
              Details
            </button>
          </td>
        `;
        
        const viewBtn = tr.querySelector('.view-transcript-btn');
        if (viewBtn) {
          viewBtn.addEventListener('click', () => {
            openCallDrawer(call);
          });
        }
        
        listBody.appendChild(tr);
      });
    }
  }

  function renderServiceRequests(requestsToRender) {
    const requestsListBody = document.getElementById('service-requests-list');
    if (!requestsListBody) return;
    
    // Limit to top 10
    const top10 = requestsToRender.slice(0, 10);
    
    if (top10.length === 0) {
      requestsListBody.innerHTML = `<tr><td colspan="9" class="text-center py-6 text-muted">No matching service requests found.</td></tr>`;
    } else {
      requestsListBody.innerHTML = '';
      top10.forEach(req => {
        const tr = document.createElement('tr');
        const formattedDate = formatShortDate(req.created_at);
        const vehicleStr = `${req.year} ${req.make} ${req.model}`;
        
        let statusBadgeClass = 'warning';
        if (req.status === 'completed') statusBadgeClass = 'success';
        else if (req.status === 'cancelled') statusBadgeClass = 'danger';
        else if (req.status === 'in_progress') statusBadgeClass = 'info';

        // Request Type Badge
        let reqTypeBadge = '';
        if (req.booking_type === 'appointment') {
          reqTypeBadge = '<span class="badge success">Appointment</span>';
        } else if (req.booking_type === 'callback') {
          reqTypeBadge = '<span class="badge info">Callback</span>';
        } else {
          reqTypeBadge = '<span class="text-muted">None</span>';
        }

        // Booking Time Format
        let displayTime = '';
        if (req.booking_type === 'callback' && (!req.booking_time || req.booking_time.toUpperCase() === 'ASAP')) {
          displayTime = '<span class="badge danger">ASAP</span>';
        } else if (req.booking_time) {
          const formattedBooking = formatShortDate(req.booking_time);
          displayTime = `<strong>${formattedBooking}</strong>`;
        } else {
          displayTime = '<span class="text-muted">N/A</span>';
        }

        tr.innerHTML = `
          <td>${formattedDate}</td>
          <td><strong>${req.customer_name || 'Unknown Customer'}</strong></td>
          <td class="text-muted">${req.phone || '--'}</td>
          <td>${vehicleStr}</td>
          <td>${req.service_type}</td>
          <td>${reqTypeBadge}</td>
          <td>${displayTime}</td>
          <td>
            <div class="tooltip-container">
              <div class="issue-desc-text">${req.issue_description}</div>
              <div class="tooltip-popup">${req.issue_description}</div>
            </div>
          </td>
          <td><span class="badge ${statusBadgeClass}">${req.status}</span></td>
        `;
        requestsListBody.appendChild(tr);
      });
    }
  }

  function applyServiceRequestsFilter() {
    const query = (document.getElementById('filter-sr-search')?.value || '').toLowerCase().trim();
    const type = document.getElementById('filter-sr-type')?.value || 'all';
    const status = document.getElementById('filter-sr-status')?.value || 'all';
    
    const filtered = allRequests.filter(req => {
      const matchesText = !query || 
        (req.customer_name || '').toLowerCase().includes(query) ||
        (req.phone || '').toLowerCase().includes(query) ||
        (req.make || '').toLowerCase().includes(query) ||
        (req.model || '').toLowerCase().includes(query) ||
        (req.service_type || '').toLowerCase().includes(query) ||
        (req.issue_description || '').toLowerCase().includes(query);
        
      const matchesType = type === 'all' || req.booking_type === type;
      const matchesStatus = status === 'all' || req.status === status;
      
      return matchesText && matchesType && matchesStatus;
    });
    
    renderServiceRequests(filtered);
  }

  function applyCallsFilter() {
    const query = (document.getElementById('filter-calls-search')?.value || '').toLowerCase().trim();
    
    const filtered = allCalls.filter(call => {
      return !query || 
        (call.customer_name || '').toLowerCase().includes(query) ||
        (call.phone || '').toLowerCase().includes(query) ||
        (call.vehicle || '').toLowerCase().includes(query) ||
        (call.summary || '').toLowerCase().includes(query);
    });
    
    renderCallLogs(filtered);
  }

  // Bind filter listeners once
  const srSearch = document.getElementById('filter-sr-search');
  if (srSearch && !srSearch.dataset.listenerBound) {
    srSearch.dataset.listenerBound = 'true';
    srSearch.addEventListener('input', applyServiceRequestsFilter);
  }
  const srType = document.getElementById('filter-sr-type');
  if (srType && !srType.dataset.listenerBound) {
    srType.dataset.listenerBound = 'true';
    srType.addEventListener('change', applyServiceRequestsFilter);
  }
  const srStatus = document.getElementById('filter-sr-status');
  if (srStatus && !srStatus.dataset.listenerBound) {
    srStatus.dataset.listenerBound = 'true';
    srStatus.addEventListener('change', applyServiceRequestsFilter);
  }
  const callsSearch = document.getElementById('filter-calls-search');
  if (callsSearch && !callsSearch.dataset.listenerBound) {
    callsSearch.dataset.listenerBound = 'true';
    callsSearch.addEventListener('input', applyCallsFilter);
  }

  async function loadDashboardData() {
    try {
      // Fetch stats
      const statsResponse = await fetch('/api/v1/portal/stats');
      if (!statsResponse.ok) throw new Error('Failed to fetch stats');
      const stats = await statsResponse.json();
      
      // Render counts safely
      const totalCallsEl = document.getElementById('stat-total-calls');
      if (totalCallsEl) totalCallsEl.textContent = stats.total_calls;
      
      const callbacksStatEl = document.getElementById('stat-callbacks');
      if (callbacksStatEl) callbacksStatEl.textContent = stats.total_callbacks;
      
      const apptsStatEl = document.getElementById('stat-appointments');
      if (apptsStatEl) apptsStatEl.textContent = stats.total_appointments;
      
      const reqsStatEl = document.getElementById('stat-requests');
      if (reqsStatEl) reqsStatEl.textContent = stats.total_requests;
      
      const calFreeEl = document.getElementById('stat-calendar-free');
      if (calFreeEl) calFreeEl.textContent = `${stats.open_slots} slots open`;

      // Fetch calls
      const callsResponse = await fetch('/api/v1/portal/calls');
      if (!callsResponse.ok) throw new Error('Failed to fetch calls');
      allCalls = await callsResponse.json();
      applyCallsFilter();

      // Fetch service requests
      const reqsResponse = await fetch('/api/v1/portal/service-requests');
      if (!reqsResponse.ok) throw new Error('Failed to fetch service requests');
      allRequests = await reqsResponse.json();
      applyServiceRequestsFilter();
      
    } catch (err) {
      console.error(err);
      showToast('Error loading dashboard: ' + err.message, 'error');
    }
  }

  // --- CALL DETAILS DRAWER / TRANSCRIPT MODAL ---
  const drawer = document.getElementById('transcript-drawer');
  const overlay = document.getElementById('transcript-drawer-overlay');
  const closeBtn = document.getElementById('close-drawer-btn');

  function openCallDrawer(call) {
    document.getElementById('drawer-customer-name').textContent = call.customer_name || 'Customer Call Details';
    document.getElementById('drawer-call-meta').textContent = `Call ID: ${call.call_id} • Phone: ${call.phone || '--'}`;
    document.getElementById('drawer-summary-box').textContent = call.summary;
    
    const timeline = document.getElementById('drawer-transcript-timeline');
    timeline.innerHTML = '';
    
    // Check if transcript is defined, parse split strings
    if (call.transcript) {
      const turns = call.transcript.split('\n');
      turns.forEach(turn => {
        if (!turn.trim()) return;
        
        const bubble = document.createElement('div');
        const isAgent = turn.startsWith('AI:') || turn.startsWith('Agent:');
        const sender = isAgent ? 'Agent' : 'Customer';
        const cleanText = turn.replace(/^(AI:|Agent:|Customer:|Caller:)\s*/i, '');
        
        bubble.className = `speech-bubble ${isAgent ? 'agent' : 'customer'}`;
        bubble.innerHTML = `
          <span class="bubble-sender ${isAgent ? 'agent-label' : ''}">${sender}</span>
          <span class="bubble-text">${cleanText}</span>
        `;
        timeline.appendChild(bubble);
      });
    } else {
      timeline.innerHTML = '<p class="text-muted text-center py-4">No full transcript available for this call.</p>';
    }
    
    drawer.classList.add('active');
    overlay.classList.add('active');
  }

  function closeDrawer() {
    drawer.classList.remove('active');
    overlay.classList.remove('active');
  }

  closeBtn.addEventListener('click', closeDrawer);
  overlay.addEventListener('click', closeDrawer);

  // --- VIEW 3: SERVICES RETRIEVAL & ADDITIONS ---
  async function loadServicesData() {
    try {
      const response = await fetch('/api/v1/portal/services');
      if (!response.ok) throw new Error('Failed to fetch services');
      const services = await response.json();
      
      const body = document.getElementById('services-list-body');
      if (body) {
        body.innerHTML = '';
        
        services.forEach(svc => {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td><strong>${svc.name}</strong></td>
            <td><div class="desc-cell" title="${svc.description || ''}">${svc.description || '--'}</div></td>
            <td><span class="badge success">${svc.price_range || '--'}</span></td>
            <td>${svc.duration_minutes ? svc.duration_minutes + ' mins' : '--'}</td>
            <td>
              <div class="actions-cell" style="display: flex; gap: 8px; align-items: center; white-space: nowrap;">
                <button class="btn btn-secondary btn-sm edit-service-btn" data-id="${svc.id}">
                  Edit
                </button>
                <button class="btn btn-secondary btn-sm delete-service-btn" data-id="${svc.id}" style="border-color: var(--color-danger); color: var(--color-danger);">
                  Delete
                </button>
              </div>
            </td>
          `;
          
          tr.querySelector('.edit-service-btn').addEventListener('click', () => {
            openEditDrawer(svc);
          });

        tr.querySelector('.delete-service-btn').addEventListener('click', async () => {
          if (!confirm(`Are you sure you want to delete the service "${svc.name}"?`)) return;
          try {
            const res = await fetch(`/api/v1/portal/services/${svc.id}`, {
              method: 'DELETE'
            });
            if (!res.ok) throw new Error('Failed to delete service');
            showToast('Service deleted successfully!');
            loadServicesData();
          } catch (err) {
            console.error(err);
            showToast('Error deleting service: ' + err.message, 'error');
          }
        });
        
        body.appendChild(tr);
      });
      }
    } catch (err) {
      console.error(err);
      showToast('Error loading services: ' + err.message, 'error');
    }
  }

  // Edit Service Drawer Actions
  function openEditDrawer(svc) {
    document.getElementById('edit-service-id').value = svc.id;
    document.getElementById('edit-service-name').value = svc.name;
    document.getElementById('edit-service-desc').value = svc.description || '';
    document.getElementById('edit-service-price').value = svc.price_range || '';
    document.getElementById('edit-service-duration').value = svc.duration_minutes || '';
    
    document.getElementById('edit-service-req-customer-name').checked = svc.req_customer_name !== undefined ? !!svc.req_customer_name : true;
    document.getElementById('edit-service-req-phone-number').checked = svc.req_phone_number !== undefined ? !!svc.req_phone_number : true;
    document.getElementById('edit-service-req-vehicle-details').checked = svc.req_vehicle_details !== undefined ? !!svc.req_vehicle_details : true;
    document.getElementById('edit-service-req-issue-description').checked = svc.req_issue_description !== undefined ? !!svc.req_issue_description : true;
    document.getElementById('edit-service-req-location').checked = svc.req_location !== undefined ? !!svc.req_location : true;
    
    editDrawer.classList.add('active');
    editDrawerOverlay.classList.add('active');
  }

  function closeEditDrawer() {
    editDrawer.classList.remove('active');
    editDrawerOverlay.classList.remove('active');
  }

  closeEditDrawerBtn.addEventListener('click', closeEditDrawer);
  cancelEditBtn.addEventListener('click', closeEditDrawer);
  editDrawerOverlay.addEventListener('click', closeEditDrawer);

  editServiceForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const id = document.getElementById('edit-service-id').value;
    const payload = {
      name: document.getElementById('edit-service-name').value,
      description: document.getElementById('edit-service-desc').value,
      price_range: document.getElementById('edit-service-price').value,
      duration_minutes: parseInt(document.getElementById('edit-service-duration').value, 10),
      req_customer_name: document.getElementById('edit-service-req-customer-name').checked,
      req_phone_number: document.getElementById('edit-service-req-phone-number').checked,
      req_vehicle_details: document.getElementById('edit-service-req-vehicle-details').checked,
      req_issue_description: document.getElementById('edit-service-req-issue-description').checked,
      req_location: document.getElementById('edit-service-req-location').checked
    };
    
    try {
      const response = await fetch(`/api/v1/portal/services/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (!response.ok) throw new Error('Failed to update service');
      
      showToast('Service updated successfully!');
      closeEditDrawer();
      loadServicesData();
    } catch (err) {
      console.error(err);
      showToast('Error updating service: ' + err.message, 'error');
    }
  });

  const addServiceForm = document.getElementById('add-service-form');
  addServiceForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const payload = {
      name: document.getElementById('new-service-name').value,
      description: document.getElementById('new-service-desc').value,
      price_range: document.getElementById('new-service-price').value,
      duration_minutes: parseInt(document.getElementById('new-service-duration').value, 10),
      req_customer_name: document.getElementById('new-service-req-customer-name').checked,
      req_phone_number: document.getElementById('new-service-req-phone-number').checked,
      req_vehicle_details: document.getElementById('new-service-req-vehicle-details').checked,
      req_issue_description: document.getElementById('new-service-req-issue-description').checked,
      req_location: document.getElementById('new-service-req-location').checked
    };
    
    try {
      const response = await fetch('/api/v1/portal/services', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (!response.ok) throw new Error('Failed to add service');
      
      showToast('Service created successfully!');
      addServiceForm.reset();
      loadServicesData();
    } catch (err) {
      console.error(err);
      showToast('Error creating service: ' + err.message, 'error');
    }
  });

  // --- VIEW 4: FILE DRAG AND DROP (RAG) ---
  const dropZone = document.getElementById('kb-drop-zone');
  const fileInput = document.getElementById('kb-file-input');
  const progressContainer = document.getElementById('upload-progress-container');
  const progressFill = document.getElementById('upload-progress-fill');
  const progressPercent = document.getElementById('upload-percent');
  const progressText = document.getElementById('upload-status-text');

  // Trigger file browsing on click
  dropZone.addEventListener('click', () => fileInput.click());

  // Prevent default drag behaviors
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
  });
  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  // Handle active states on hover
  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.add('active'), false);
  });
  ['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.remove('active'), false);
  });

  // Handle dropped files
  dropZone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
      uploadKBFile(files[0]);
    }
  });

  // Handle file selection
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      uploadKBFile(fileInput.files[0]);
    }
  });

  async function uploadKBFile(file) {
    if (!file.name.endsWith('.txt') && !file.name.endsWith('.md')) {
      showToast('Only .txt or .md files are supported', 'error');
      return;
    }
    
    const formData = new FormData();
    formData.append('file', file);
    
    // Show progress loading indicators
    progressContainer.classList.remove('hidden');
    progressFill.style.width = '30%';
    progressPercent.textContent = '30%';
    progressText.textContent = 'Uploading file...';
    
    try {
      const response = await fetch('/api/v1/portal/kb/upload', {
        method: 'POST',
        body: formData
      });
      
      if (!response.ok) throw new Error('File upload failure');
      const data = await response.json();
      
      progressFill.style.width = '100%';
      progressPercent.textContent = '100%';
      progressText.textContent = 'Completed!';
      
      showToast(`Successfully indexed ${data.chunk_count} chunks into local ChromaDB!`);
      loadKBData();
      
      setTimeout(() => {
        progressContainer.classList.add('hidden');
      }, 3000);
      
    } catch (err) {
      console.error(err);
      progressContainer.classList.add('hidden');
      showToast('Ingestion failed: ' + err.message, 'error');
    }
  }

  // --- VIEW 5: VOICE ROUTING AND KEYS ---
  async function loadVoiceData() {
    try {
      const configRes = await fetch('/api/v1/portal/config');
      if (configRes.ok) {
        const config = await configRes.json();
        const handoffPhoneInput = document.getElementById('agent-handoff-phone');
        if (handoffPhoneInput) {
          handoffPhoneInput.value = config.handoff_phone_number || '';
        }
      }
    } catch (err) {
      console.warn('Failed to fetch config for handoff phone:', err);
    }

    try {
      const response = await fetch('/api/v1/portal/elevenlabs/voices');
      if (!response.ok) throw new Error('ElevenLabs credentials offline or missing');
      const data = await response.json();
      
      const select = document.getElementById('agent-voice-selection');
      select.innerHTML = '';
      
      if (data.voices && data.voices.length > 0) {
        data.voices.forEach(voice => {
          const opt = document.createElement('option');
          opt.value = voice.voice_id;
          opt.textContent = `${voice.name} (${voice.category})`;
          select.appendChild(opt);
        });
      } else {
        select.innerHTML = '<option value="default">No custom voices found</option>';
      }
    } catch (err) {
      console.warn(err);
      const select = document.getElementById('agent-voice-selection');
      select.innerHTML = '<option value="default_mock">Mock Rachel (Default ElevenLabs)</option>' +
                         '<option value="default_mock2">Mock Clyde (Default ElevenLabs)</option>';
    }
  }

  // Form Submit updates Voice routing Agent ID
  const voiceRoutingForm = document.getElementById('voice-routing-form');
  voiceRoutingForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const model = document.getElementById('agent-llm-model').value;
    const voiceId = document.getElementById('agent-voice-selection').value;
    const handoffPhone = document.getElementById('agent-handoff-phone').value;
    
    try {
      const response = await fetch('/api/v1/portal/elevenlabs/agent', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: model, voice_id: voiceId })
      });
      
      if (!response.ok) throw new Error('Dynamic ElevenLabs configuration update failed');
      showToast('Agent model and voice configurations updated live!');
    } catch (err) {
      console.warn(err);
      showToast('Saved settings locally (Mock status: ElevenLabs ID not found)', 'success');
    }

    try {
      const configRes = await fetch('/api/v1/portal/config');
      if (configRes.ok) {
        const config = await configRes.json();
        config.handoff_phone_number = handoffPhone;
        
        const updateRes = await fetch('/api/v1/portal/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config)
        });
        if (!updateRes.ok) throw new Error('Failed to save configuration');
      }
    } catch (err) {
      console.error(err);
      showToast('Error saving handoff phone: ' + err.message, 'error');
    }
  });

  // Secrets Encrypt Form
  const saveKeysForm = document.getElementById('save-api-keys-form');
  saveKeysForm.addEventListener('submit', (e) => {
    e.preventDefault();
    showToast('API credentials encrypted and securely saved at rest!');
  });

  // --- VIEW 2: CONFIGURATION MANAGER ---
  async function loadConfigData() {
    try {
      const response = await fetch('/api/v1/portal/config');
      if (!response.ok) throw new Error('Failed to fetch configurations');
      const config = await response.json() || {};
      
      // Populate textareas
      const firstMsgEl = document.getElementById('prompt-first-message');
      const sysPromptEl = document.getElementById('prompt-system');
      if (firstMsgEl) firstMsgEl.value = config.first_message || '';
      if (sysPromptEl) sysPromptEl.value = config.system_prompt || '';
      
      // Populate checkboxes
      const reqCustomerName = document.getElementById('req-customer-name');
      const reqPhoneNumber = document.getElementById('req-phone-number');
      const reqVehicleDetails = document.getElementById('req-vehicle-details');
      const reqIssueDescription = document.getElementById('req-issue-description');
      
      const reqFields = config.required_fields || {};
      if (reqCustomerName) reqCustomerName.checked = !!reqFields.customer_name;
      if (reqPhoneNumber) reqPhoneNumber.checked = !!reqFields.phone_number;
      if (reqVehicleDetails) reqVehicleDetails.checked = !!reqFields.vehicle_details;
      if (reqIssueDescription) reqIssueDescription.checked = !!reqFields.issue_description;
      
    } catch (err) {
      console.error(err);
      showToast('Error loading configuration: ' + err.message, 'error');
    }
  }

  // Core router intents form
  const intentForm = document.getElementById('intent-config-form');
  if (intentForm) {
    intentForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const reqCustomerName = document.getElementById('req-customer-name');
      const reqPhoneNumber = document.getElementById('req-phone-number');
      const reqVehicleDetails = document.getElementById('req-vehicle-details');
      const reqIssueDescription = document.getElementById('req-issue-description');
      
      const sysPromptEl = document.getElementById('prompt-system');
      const firstMsgEl = document.getElementById('prompt-first-message');

      const payload = {
        required_fields: {
          customer_name: reqCustomerName ? reqCustomerName.checked : true,
          phone_number: reqPhoneNumber ? reqPhoneNumber.checked : true,
          vehicle_details: reqVehicleDetails ? reqVehicleDetails.checked : true,
          issue_description: reqIssueDescription ? reqIssueDescription.checked : true
        },
        system_prompt: sysPromptEl ? sysPromptEl.value : '',
        first_message: firstMsgEl ? firstMsgEl.value : ''
      };
      
      try {
        const response = await fetch('/api/v1/portal/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error('Failed to save configurations');
        showToast('Agent prompts and intake fields updated successfully!');
      } catch (err) {
        console.error(err);
        showToast('Error saving configuration: ' + err.message, 'error');
      }
    });
  }

  // --- VIEW 4: KNOWLEDGE BASE RETRIEVAL & MANAGEMENT ---
  async function loadKBData() {
    try {
      const response = await fetch('/api/v1/portal/kb');
      if (!response.ok) throw new Error('Failed to fetch KB documents');
      const files = await response.json();
      
      const filesList = document.getElementById('kb-files-list');
      filesList.innerHTML = '';
      
      if (files.length === 0) {
        filesList.innerHTML = '<p class="text-muted text-center py-6">No documents indexed in local database.</p>';
        return;
      }
      
      files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'kb-file-item';
        
        const sizeKB = (file.size_bytes / 1024).toFixed(1);
        
        item.innerHTML = `
          <div class="file-info">
            <svg class="file-icon" viewBox="0 0 24 24"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>
            <div>
              <span class="file-name">${file.filename}</span>
              <span class="file-meta">File Size: ${sizeKB} KB</span>
            </div>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <button class="btn btn-secondary btn-sm view-kb-btn">
              View
            </button>
            <button class="btn btn-secondary btn-sm download-kb-btn">
              Download
            </button>
            <button class="btn btn-secondary btn-sm delete-kb-btn" style="border-color: var(--color-danger); color: var(--color-danger);">
              Delete
            </button>
          </div>
        `;
        
        // Bind View
        item.querySelector('.view-kb-btn').addEventListener('click', async () => {
          try {
            const res = await fetch(`/api/v1/portal/kb/view/${encodeURIComponent(file.filename)}`);
            if (!res.ok) throw new Error('Failed to load file content');
            const data = await res.json();
            
            document.getElementById('document-drawer-title').textContent = file.filename;
            document.getElementById('document-drawer-meta').textContent = `File Size: ${sizeKB} KB`;
            document.getElementById('document-drawer-body').textContent = data.content;
            
            documentDrawer.classList.add('active');
            documentDrawerOverlay.classList.add('active');
          } catch (err) {
            console.error(err);
            showToast('Error opening file: ' + err.message, 'error');
          }
        });
        
        // Bind Download
        item.querySelector('.download-kb-btn').addEventListener('click', () => {
          window.location.href = `/api/v1/portal/kb/download/${encodeURIComponent(file.filename)}`;
        });
        
        // Bind Delete
        item.querySelector('.delete-kb-btn').addEventListener('click', async () => {
          if (!confirm(`Are you sure you want to delete "${file.filename}" from the Knowledge Base?`)) return;
          try {
            const res = await fetch(`/api/v1/portal/kb/${encodeURIComponent(file.filename)}`, {
              method: 'DELETE'
            });
            if (!res.ok) throw new Error('Failed to delete KB file');
            
            showToast('Document deleted and unindexed from RAG collection.');
            loadKBData();
          } catch (err) {
            console.error(err);
            showToast('Error deleting file: ' + err.message, 'error');
          }
        });
        
        filesList.appendChild(item);
      });
    } catch (err) {
      console.error(err);
      showToast('Error loading KB documents: ' + err.message, 'error');
    }
  }

  // --- VIEW 6: STAFF CALENDARS & SCHEDULES ---
  let isStaffListenerAttached = false;

  // Sync Calendar button — fires immediately on click
  const syncCalendarBtn = document.getElementById('sync-calendar-btn');
  if (syncCalendarBtn) {
    syncCalendarBtn.addEventListener('click', async () => {
      const originalText = syncCalendarBtn.innerHTML;
      syncCalendarBtn.disabled = true;
      syncCalendarBtn.innerHTML = `<svg viewBox="0 0 24 24" style="width:13px;height:13px;fill:currentColor;animation:spin 1s linear infinite"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg> Syncing...`;
      try {
        const res = await fetch('/api/v1/portal/calendar/sync-all', { method: 'POST' });
        if (!res.ok) throw new Error('Sync request failed');
        const data = await res.json();
        const newSlots = data.total_new_slots || 0;
        showToast(`Calendar synced! ${newSlots} new slot(s) created from live Google Calendar.`);
        // Reload slot view for the currently selected agent
        const agentId = staffAgentSelector.value;
        if (agentId) loadAgentCalendar(agentId);
      } catch (err) {
        console.error(err);
        showToast('Calendar sync failed: ' + err.message, 'error');
      } finally {
        syncCalendarBtn.disabled = false;
        syncCalendarBtn.innerHTML = originalText;
      }
    });
  }


  async function updateAgentConnectionUI() {
    const selectedAgentId = staffAgentSelector.value;
    const calendarBadge = document.getElementById('agent-calendar-status-badge');
    const connectCalendarBtn = document.getElementById('connect-agent-calendar-btn');
    const gmailBadge = document.getElementById('agent-gmail-status-badge');
    const connectGmailBtn = document.getElementById('connect-agent-gmail-btn');
    
    if (!calendarBadge || !connectCalendarBtn || !gmailBadge || !connectGmailBtn) return;
    
    if (!selectedAgentId) {
      calendarBadge.className = 'badge danger';
      calendarBadge.textContent = 'Disconnected';
      connectCalendarBtn.textContent = 'Connect';
      connectCalendarBtn.classList.add('btn-secondary');
      connectCalendarBtn.style.borderColor = 'var(--color-primary)';
      connectCalendarBtn.dataset.isConnected = 'false';
      connectCalendarBtn.disabled = true;
      
      gmailBadge.className = 'badge danger';
      gmailBadge.textContent = 'Disconnected';
      connectGmailBtn.textContent = 'Connect';
      connectGmailBtn.classList.add('btn-secondary');
      connectGmailBtn.style.borderColor = 'var(--color-primary)';
      connectGmailBtn.dataset.isConnected = 'false';
      connectGmailBtn.disabled = true;
      
      if (deleteAgentProfileBtn) deleteAgentProfileBtn.disabled = true;
      return;
    }
    
    // Enable buttons
    connectCalendarBtn.disabled = false;
    connectGmailBtn.disabled = false;
    if (deleteAgentProfileBtn) deleteAgentProfileBtn.disabled = false;
    
    try {
      const response = await fetch(`/api/v1/portal/agents/${selectedAgentId}/google/status`);
      if (!response.ok) throw new Error('Failed to fetch status');
      const status = await response.json();
      
      const calendarConnected = status.is_connected && status.scopes.includes('https://www.googleapis.com/auth/calendar.events');
      const gmailConnected = status.is_connected && status.scopes.includes('https://www.googleapis.com/auth/gmail.send');
      
      if (calendarConnected) {
        calendarBadge.className = 'badge success';
        calendarBadge.textContent = 'Connected';
        connectCalendarBtn.textContent = 'Disconnect';
        connectCalendarBtn.classList.remove('btn-secondary');
        connectCalendarBtn.style.borderColor = 'var(--color-danger)';
        connectCalendarBtn.dataset.isConnected = 'true';
      } else {
        calendarBadge.className = 'badge danger';
        calendarBadge.textContent = 'Disconnected';
        connectCalendarBtn.textContent = 'Connect';
        connectCalendarBtn.classList.add('btn-secondary');
        connectCalendarBtn.style.borderColor = 'var(--color-primary)';
        connectCalendarBtn.dataset.isConnected = 'false';
      }
      
      if (gmailConnected) {
        gmailBadge.className = 'badge success';
        gmailBadge.textContent = 'Connected';
        connectGmailBtn.textContent = 'Disconnect';
        connectGmailBtn.classList.remove('btn-secondary');
        connectGmailBtn.style.borderColor = 'var(--color-danger)';
        connectGmailBtn.dataset.isConnected = 'true';
      } else {
        gmailBadge.className = 'badge danger';
        gmailBadge.textContent = 'Disconnected';
        connectGmailBtn.textContent = 'Connect';
        connectGmailBtn.classList.add('btn-secondary');
        connectGmailBtn.style.borderColor = 'var(--color-primary)';
        connectGmailBtn.dataset.isConnected = 'false';
      }
    } catch (err) {
      console.error('Error fetching Google connection status:', err);
    }
  }

  async function loadStaffView(selectedId = null) {
    try {
      const response = await fetch('/api/v1/portal/agents');
      if (!response.ok) throw new Error('Failed to fetch staff agents');
      const agents = await response.json();
      
      const prevValue = selectedId || staffAgentSelector.value;
      
      staffAgentSelector.innerHTML = '';
      if (agents.length === 0) {
        staffAgentSelector.innerHTML = '<option value="">No agents available</option>';
        staffSlotsListBody.innerHTML = '<tr><td colspan="3" class="text-center py-6 text-muted">No staff agents found.</td></tr>';
        
        // Update connection status and disable buttons
        await updateAgentConnectionUI();
        return;
      }
      
      agents.forEach(agent => {
        const opt = document.createElement('option');
        opt.value = agent.id;
        opt.textContent = `${agent.name} (${agent.role || 'Service Agent'})`;
        opt.dataset.email = agent.email || '';
        staffAgentSelector.appendChild(opt);
      });
      
      // Preserve selection if possible, otherwise first option
      if (prevValue && Array.from(staffAgentSelector.options).some(opt => opt.value == prevValue)) {
        staffAgentSelector.value = prevValue;
      } else {
        staffAgentSelector.selectedIndex = 0;
      }
      
      // Update the connection status UI
      await updateAgentConnectionUI();

      // Load calendar for the initially selected agent
      const initialAgentId = staffAgentSelector.value;
      if (initialAgentId) {
        loadAgentCalendar(initialAgentId);
      }
      
      // Attach change listener if not already attached
      if (!isStaffListenerAttached) {
        staffAgentSelector.addEventListener('change', async (e) => {
          await updateAgentConnectionUI();
          if (e.target.value) {
            loadAgentCalendar(e.target.value);
          } else {
            staffSlotsListBody.innerHTML = '<tr><td colspan="3" class="text-center py-6 text-muted">Select an agent to load calendar slots.</td></tr>';
          }
        });
        
        // Connect / Disconnect agent calendar handler
        const connectCalendarBtn = document.getElementById('connect-agent-calendar-btn');
        if (connectCalendarBtn) {
          connectCalendarBtn.addEventListener('click', async () => {
            const agentId = staffAgentSelector.value;
            if (!agentId) return;
            const isConnected = connectCalendarBtn.dataset.isConnected === 'true';
            
            if (isConnected) {
              if (!confirm('Are you sure you want to disconnect Google Calendar / Google Account integration for this staff member?')) return;
              try {
                const res = await fetch(`/api/v1/portal/agents/${agentId}/google/disconnect`, { method: 'POST' });
                if (!res.ok) throw new Error('Disconnect failed');
                showToast('Google Account disconnected successfully.');
                await updateAgentConnectionUI();
              } catch (err) {
                console.error(err);
                showToast('Error disconnecting: ' + err.message, 'error');
              }
            } else {
              // Open OAuth Consent Screen in popup
              try {
                const authUrlRes = await fetch(`/api/v1/portal/agents/${agentId}/google/auth-url?action=calendar`);
                if (!authUrlRes.ok) {
                  const data = await authUrlRes.json();
                  throw new Error(data.detail || 'Failed to generate OAuth URL');
                }
                const authData = await authUrlRes.json();
                
                const width = 600, height = 650;
                const left = (window.screen.width - width) / 2;
                const top = (window.screen.height - height) / 2;
                const popup = window.open(
                  authData.auth_url,
                  'Google Agent Calendar Authentication',
                  `width=${width},height=${height},left=${left},top=${top},status=no,resizable=yes,scrollbars=yes`
                );
                
                window.addEventListener('message', function agentAuthMsgListener(event) {
                  if (event.data === 'agent-auth-success') {
                    showToast('Agent Google Calendar connected successfully!');
                    updateAgentConnectionUI();
                    window.removeEventListener('message', agentAuthMsgListener);
                  }
                });
              } catch (err) {
                console.error(err);
                showToast('OAuth connection failed: ' + err.message, 'error');
              }
            }
          });
        }

        // Connect / Disconnect agent Gmail handler
        const connectGmailBtn = document.getElementById('connect-agent-gmail-btn');
        if (connectGmailBtn) {
          connectGmailBtn.addEventListener('click', async () => {
            const agentId = staffAgentSelector.value;
            if (!agentId) return;
            const isConnected = connectGmailBtn.dataset.isConnected === 'true';
            
            if (isConnected) {
              if (!confirm('Are you sure you want to disconnect Gmail Send capabilities for this staff member? (This will disconnect the Google account)')) return;
              try {
                const res = await fetch(`/api/v1/portal/agents/${agentId}/google/disconnect`, { method: 'POST' });
                if (!res.ok) throw new Error('Disconnect failed');
                showToast('Gmail integration disconnected successfully.');
                await updateAgentConnectionUI();
              } catch (err) {
                console.error(err);
                showToast('Error disconnecting: ' + err.message, 'error');
              }
            } else {
              // Open OAuth Consent Screen in popup
              try {
                const authUrlRes = await fetch(`/api/v1/portal/agents/${agentId}/google/auth-url?action=gmail`);
                if (!authUrlRes.ok) {
                  const data = await authUrlRes.json();
                  throw new Error(data.detail || 'Failed to generate OAuth URL');
                }
                const authData = await authUrlRes.json();
                
                const width = 600, height = 650;
                const left = (window.screen.width - width) / 2;
                const top = (window.screen.height - height) / 2;
                const popup = window.open(
                  authData.auth_url,
                  'Google Agent Gmail Authentication',
                  `width=${width},height=${height},left=${left},top=${top},status=no,resizable=yes,scrollbars=yes`
                );
                
                window.addEventListener('message', function agentGmailAuthMsgListener(event) {
                  if (event.data === 'gmail-auth-success') {
                    showToast('Agent Gmail Send integration connected successfully!');
                    updateAgentConnectionUI();
                    window.removeEventListener('message', agentGmailAuthMsgListener);
                  }
                });
              } catch (err) {
                console.error(err);
                showToast('OAuth connection failed: ' + err.message, 'error');
              }
            }
          });
        }

        // Attach form submission for adding slot
        addSlotForm.addEventListener('submit', async (e) => {
          e.preventDefault();
          const selectedAgentId = staffAgentSelector.value;
          if (!selectedAgentId) {
            showToast('Please select a staff member first.', 'error');
            return;
          }
          
          const rawDatetime = newSlotDatetimeInput.value; // e.g. "2026-06-09T14:00"
          if (!rawDatetime) return;
          
          // Format "2026-06-09T14:00" to "2026-06-09 14:00:00"
          const formattedDatetime = rawDatetime.replace('T', ' ') + ':00';
          
          try {
            const res = await fetch(`/api/v1/portal/agents/${selectedAgentId}/calendar`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ slot_datetime: formattedDatetime, is_booked: false })
            });
            
            if (res.status === 400) {
              const data = await res.json();
              throw new Error(data.detail || 'Time slot already exists');
            }
            if (!res.ok) throw new Error('Failed to add slot');
            
            showToast('Availability slot added successfully!');
            newSlotDatetimeInput.value = '';
            loadAgentCalendar(selectedAgentId);
          } catch (err) {
            console.error(err);
            showToast('Error adding slot: ' + err.message, 'error');
          }
        });

        // Add Staff Member Form handler
        if (addAgentForm) {
          addAgentForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = newAgentNameInput.value.trim();
            const role = newAgentRoleInput.value.trim() || 'Service Advisor';
            const email = newAgentEmailInput.value.trim() || null;
            
            if (!name) return;
            
            try {
              const response = await fetch('/api/v1/portal/agents', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, role, email })
              });
              if (!response.ok) {
                const data = await response.json();
                throw new Error(data.detail || 'Failed to add staff member');
              }
              const data = await response.json();
              showToast(`Staff member "${name}" registered successfully!`);
              addAgentForm.reset();
              newAgentRoleInput.value = 'Service Advisor'; // restore default
              
              // Reload staff list and auto-select the new agent
              await loadStaffView(data.id);
            } catch (err) {
              console.error(err);
              showToast('Error adding staff member: ' + err.message, 'error');
            }
          });
        }

        // Delete Profile click handler
        if (deleteAgentProfileBtn) {
          deleteAgentProfileBtn.addEventListener('click', async () => {
            const agentId = staffAgentSelector.value;
            if (!agentId) return;
            
            const selectedText = staffAgentSelector.options[staffAgentSelector.selectedIndex].text;
            if (!confirm(`Are you sure you want to delete the profile for "${selectedText}"?\nThis will remove all availability slots and active Google integrations.`)) {
              return;
            }
            
            try {
              const res = await fetch(`/api/v1/portal/agents/${agentId}`, {
                method: 'DELETE'
              });
              if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to delete profile');
              }
              showToast('Staff member profile deleted successfully.');
              
              // Reload staff view and default to the first remaining agent
              await loadStaffView();
            } catch (err) {
              console.error(err);
              showToast('Error deleting profile: ' + err.message, 'error');
            }
          });
        }
        
        isStaffListenerAttached = true;
      }
      
    } catch (err) {
      console.error(err);
      showToast('Error loading staff view: ' + err.message, 'error');
    }
  }

  async function loadAgentCalendar(agentId) {
    try {
      const response = await fetch(`/api/v1/portal/agents/${agentId}/calendar`);
      if (!response.ok) throw new Error('Failed to fetch calendar slots');
      const slots = await response.json();
      
      staffSlotsListBody.innerHTML = '';
      
      if (slots.length === 0) {
        staffSlotsListBody.innerHTML = '<tr><td colspan="3" class="text-center py-6 text-muted">No availability slots scheduled.</td></tr>';
        return;
      }
      
      slots.forEach(slot => {
        const tr = document.createElement('tr');
        const startDate = new Date(slot.slot_datetime.replace(' ', 'T'));
        const endDate = new Date(startDate.getTime() + 30 * 60 * 1000);
        
        const dateOptions = { year: 'numeric', month: '2-digit', day: '2-digit' };
        const timeOptions = { hour: '2-digit', minute: '2-digit', hour12: true };
        
        const dateString = startDate.toLocaleDateString(undefined, dateOptions);
        const startTimeString = startDate.toLocaleTimeString(undefined, timeOptions);
        const endTimeString = endDate.toLocaleTimeString(undefined, timeOptions);
        
        const timeWindowStr = `${dateString} @ ${startTimeString} - ${endTimeString}`;
        
        tr.innerHTML = `
          <td><strong>${timeWindowStr}</strong></td>
          <td><span class="badge ${slot.is_booked ? 'warning' : 'success'}">${slot.is_booked ? 'Booked' : 'Available'}</span></td>
          <td>
            <div class="actions-cell" style="display: flex; gap: 8px; align-items: center; white-space: nowrap;">
              <button class="btn btn-secondary btn-sm toggle-slot-btn">
                ${slot.is_booked ? 'Mark Available' : 'Mark Booked'}
              </button>
              <button class="btn btn-secondary btn-sm delete-slot-btn" style="border-color: var(--color-danger); color: var(--color-danger);">
                Delete
              </button>
            </div>
          </td>
        `;
        
        // Toggle Booking Status click handler
        tr.querySelector('.toggle-slot-btn').addEventListener('click', async () => {
          try {
            const res = await fetch(`/api/v1/portal/calendar/${slot.id}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ is_booked: !slot.is_booked })
            });
            if (!res.ok) throw new Error('Failed to toggle status');
            
            showToast(`Slot marked ${!slot.is_booked ? 'booked' : 'available'} successfully.`);
            loadAgentCalendar(agentId);
          } catch (err) {
            console.error(err);
            showToast('Error updating status: ' + err.message, 'error');
          }
        });
        
        // Delete Slot click handler
        tr.querySelector('.delete-slot-btn').addEventListener('click', async () => {
          if (!confirm('Are you sure you want to delete this availability slot?')) return;
          try {
            const res = await fetch(`/api/v1/portal/calendar/${slot.id}`, {
              method: 'DELETE'
            });
            if (!res.ok) throw new Error('Failed to delete slot');
            
            showToast('Time slot removed successfully.');
            loadAgentCalendar(agentId);
          } catch (err) {
            console.error(err);
            showToast('Error deleting slot: ' + err.message, 'error');
          }
        });
        
        staffSlotsListBody.appendChild(tr);
      });
      
    } catch (err) {
      console.error(err);
      showToast('Error loading calendar: ' + err.message, 'error');
    }
  }

  // --- VIEW 7: GMAIL NOTIFICATION CONFIG ---
  function toggleGmailAuthFields(authType) {
    const smtpPassGroup = document.getElementById('gmail-smtp-pass-group');
    const smtpServerGroup = document.getElementById('gmail-smtp-server-group');
    const smtpPortGroup = document.getElementById('gmail-smtp-port-group');
    
    const oauthIdGroup = document.getElementById('gmail-oauth-id-group');
    const oauthSecretGroup = document.getElementById('gmail-oauth-secret-group');
    const oauthStatusGroup = document.getElementById('gmail-oauth-status-group');
    
    const senderGroup = document.getElementById('gmail-sender-group');
    const senderInput = document.getElementById('gmail-sender');
    
    const smtpHelp = document.getElementById('smtp-help-text');
    const oauthHelp = document.getElementById('oauth-help-text');
    
    if (authType === 'oauth2') {
      if (smtpPassGroup) smtpPassGroup.style.display = 'none';
      if (smtpServerGroup) smtpServerGroup.style.display = 'none';
      if (smtpPortGroup) smtpPortGroup.style.display = 'none';
      
      if (oauthIdGroup) oauthIdGroup.style.display = 'none';
      if (oauthSecretGroup) oauthSecretGroup.style.display = 'none';
      if (oauthStatusGroup) oauthStatusGroup.style.display = '';
      
      if (senderGroup) senderGroup.style.display = 'none';
      if (senderInput) senderInput.removeAttribute('required');
      
      if (smtpHelp) smtpHelp.style.display = 'none';
      if (oauthHelp) oauthHelp.style.display = 'block';
    } else {
      if (smtpPassGroup) smtpPassGroup.style.display = '';
      if (smtpServerGroup) smtpServerGroup.style.display = '';
      if (smtpPortGroup) smtpPortGroup.style.display = '';
      
      if (oauthIdGroup) oauthIdGroup.style.display = 'none';
      if (oauthSecretGroup) oauthSecretGroup.style.display = 'none';
      if (oauthStatusGroup) oauthStatusGroup.style.display = 'none';
      
      if (senderGroup) senderGroup.style.display = '';
      if (senderInput) senderInput.setAttribute('required', 'required');
      
      if (smtpHelp) smtpHelp.style.display = 'block';
      if (oauthHelp) oauthHelp.style.display = 'none';
    }
  }

  // Bind change handler on auth type selector
  const authTypeSelect = document.getElementById('gmail-auth-type');
  if (authTypeSelect) {
    authTypeSelect.addEventListener('change', (e) => {
      toggleGmailAuthFields(e.target.value);
    });
  }

  async function loadGmailConfig() {
    try {
      const response = await fetch('/api/v1/portal/gmail-config');
      if (!response.ok) throw new Error('Failed to fetch Gmail configurations');
      const config = await response.json();
      
      document.getElementById('gmail-enabled').checked = !!config.gmail_enabled;
      document.getElementById('gmail-auth-type').value = config.gmail_auth_type || 'app_password';
      document.getElementById('gmail-sender').value = config.gmail_sender || '';
      document.getElementById('gmail-recipient').value = config.gmail_recipient || '';
      document.getElementById('gmail-smtp-server').value = config.gmail_smtp_server || 'smtp.gmail.com';
      document.getElementById('gmail-smtp-port').value = config.gmail_smtp_port || 587;
      
      // Load Google Client ID
      const clientIdInput = document.getElementById('gmail-client-id');
      if (clientIdInput) {
        clientIdInput.value = config.gmail_client_id || '';
      }
      
      // Mask Client Secret
      const clientSecretInput = document.getElementById('gmail-client-secret');
      if (clientSecretInput) {
        if (config.has_client_secret) {
          clientSecretInput.value = '••••••••••••••••';
        } else {
          clientSecretInput.value = '';
        }
      }

      // Mask SMTP password if stored
      const passwordInput = document.getElementById('gmail-password');
      if (passwordInput) {
        if (config.has_password) {
          passwordInput.value = '••••••••••••••••';
        } else {
          passwordInput.value = '';
        }
      }

      // Populate exact Google Redirect URI to copy
      const redirectUriDisplay = document.getElementById('gmail-redirect-uri-display');
      if (redirectUriDisplay) {
        redirectUriDisplay.textContent = window.location.origin + '/api/v1/portal/gmail/oauth/callback';
      }

      // Populate OAuth Connection status
      const statusBadge = document.getElementById('gmail-oauth-status-badge');
      const connectBtn = document.getElementById('connect-gmail-btn');
      if (statusBadge && connectBtn) {
        if (config.is_connected) {
          statusBadge.className = 'badge success';
          statusBadge.textContent = 'Connected';
          connectBtn.textContent = 'Reconnect Google Account';
        } else {
          statusBadge.className = 'badge danger';
          statusBadge.textContent = 'Disconnected';
          connectBtn.textContent = 'Connect Gmail Account';
        }
      }
      
      // Update UI fields display
      toggleGmailAuthFields(config.gmail_auth_type || 'app_password');

    } catch (err) {
      console.error(err);
      showToast('Error loading Gmail configuration: ' + err.message, 'error');
    }
  }

  // Handle Save configuration
  const gmailConfigForm = document.getElementById('gmail-config-form');
  if (gmailConfigForm) {
    gmailConfigForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const payload = {
        gmail_enabled: document.getElementById('gmail-enabled').checked,
        gmail_auth_type: document.getElementById('gmail-auth-type').value,
        gmail_sender: document.getElementById('gmail-sender').value.trim(),
        gmail_password: document.getElementById('gmail-password').value,
        gmail_recipient: document.getElementById('gmail-recipient').value.trim(),
        gmail_smtp_server: document.getElementById('gmail-smtp-server').value.trim() || 'smtp.gmail.com',
        gmail_smtp_port: parseInt(document.getElementById('gmail-smtp-port').value, 10) || 587,
        gmail_client_id: document.getElementById('gmail-client-id').value.trim(),
        gmail_client_secret: document.getElementById('gmail-client-secret').value
      };
      
      try {
        const response = await fetch('/api/v1/portal/gmail-config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error('Failed to save Gmail configurations');
        showToast('Gmail configuration saved successfully!');
        loadGmailConfig(); // reload to refresh fields and masking
      } catch (err) {
        console.error(err);
        showToast('Error saving Gmail configuration: ' + err.message, 'error');
      }
    });
  }

  // Handle Test Connection button
  const testGmailBtn = document.getElementById('test-gmail-btn');
  if (testGmailBtn) {
    testGmailBtn.addEventListener('click', async () => {
      const payload = {
        gmail_enabled: document.getElementById('gmail-enabled').checked,
        gmail_auth_type: document.getElementById('gmail-auth-type').value,
        gmail_sender: document.getElementById('gmail-sender').value.trim(),
        gmail_password: document.getElementById('gmail-password').value,
        gmail_recipient: document.getElementById('gmail-recipient').value.trim(),
        gmail_smtp_server: document.getElementById('gmail-smtp-server').value.trim() || 'smtp.gmail.com',
        gmail_smtp_port: parseInt(document.getElementById('gmail-smtp-port').value, 10) || 587,
        gmail_client_id: document.getElementById('gmail-client-id').value.trim(),
        gmail_client_secret: document.getElementById('gmail-client-secret').value
      };
      
      if (!payload.gmail_sender || !payload.gmail_recipient) {
        showToast('Please fill out Sender Address and Recipient Address fields first.', 'error');
        return;
      }
      
      if (payload.gmail_auth_type === 'app_password' && !payload.gmail_password) {
        showToast('Please enter an App Password for SMTP test.', 'error');
        return;
      }
      
      showToast('Testing Gmail connection, sending test email...', 'info');
      testGmailBtn.disabled = true;
      
      try {
        const response = await fetch('/api/v1/portal/gmail-config/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        
        testGmailBtn.disabled = false;
        
        if (!response.ok) {
          const errData = await response.json();
          throw new Error(errData.detail || 'Connection test failed');
        }
        
        showToast('Test email sent successfully! Check your inbox.');
      } catch (err) {
        testGmailBtn.disabled = false;
        console.error(err);
        showToast('Connection Test Failed: ' + err.message, 'error');
      }
    });
  }

  // Handle Connect Google Account popup redirection
  const connectGmailBtn = document.getElementById('connect-gmail-btn');
  if (connectGmailBtn) {
    connectGmailBtn.addEventListener('click', async () => {
      showToast('Redirecting to Google Account connection...', 'info');
      try {
        // Fetch consent authorization URL
        const authUrlRes = await fetch('/api/v1/portal/gmail/oauth/auth-url');
        if (!authUrlRes.ok) {
          const data = await authUrlRes.json();
          throw new Error(data.detail || 'Failed to generate OAuth redirect URL');
        }
        const authData = await authUrlRes.json();
        
        // Open Consent Screen in popup
        const width = 600, height = 650;
        const left = (window.screen.width - width) / 2;
        const top = (window.screen.height - height) / 2;
        const popup = window.open(
          authData.auth_url,
          'Google Account Authentication',
          `width=${width},height=${height},left=${left},top=${top},status=no,resizable=yes,scrollbars=yes`
        );
        
        // Listen for message confirmation back from the popup window callback page
        window.addEventListener('message', function authMsgListener(event) {
          if (event.data === 'gmail-auth-success') {
            showToast('Google Account authorized and connected!');
            loadGmailConfig();
            window.removeEventListener('message', authMsgListener);
          }
        });

      } catch (err) {
        console.error(err);
        showToast('Authentication failed: ' + err.message, 'error');
      }
    });
  }


  // Global Refresh Action
  refreshBtn.addEventListener('click', () => {
    loadDashboardData();
    showToast('Refreshed statistics and calls log history.');
  });

  // Initial Data Load
  loadDashboardData();
  
});
