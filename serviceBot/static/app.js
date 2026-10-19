document.addEventListener('DOMContentLoaded', () => {
  
  // Local state for tables & pagination
  let allCalls = [];
  let allRequests = [];
  let srCurrentPage = 1;
  let srPageSize = 10;
  let callsCurrentPage = 1;
  let callsPageSize = 10;

  // Availability can contact calendars: serialize explicit requests across portal flows.
  let availabilityTail = Promise.resolve();
  const availabilityInFlight = new Map();
  function requestAvailableAgents(requestId, isCurrent = () => true) {
    const key = String(requestId);
    const existing = availabilityInFlight.get(key);
    if (existing) {
      existing.consumers.push(isCurrent);
      return existing.operation;
    }
    const entry = { consumers: [isCurrent], operation: null };
    const operation = availabilityTail.catch(() => {}).then(async () => {
      if (!entry.consumers.some(current => current())) return null;
      const response = await fetch(`/api/v1/portal/service-requests/${requestId}/available-agents`);
      if (!response.ok) throw new Error('Could not load live agent availability');
      return response.json();
    });
    entry.operation = operation;
    availabilityInFlight.set(key, entry);
    availabilityTail = operation.catch(() => {});
    operation.finally(() => {
      if (availabilityInFlight.get(key) === entry) availabilityInFlight.delete(key);
    }).catch(() => {});
    return operation;
  }

  // Business Timezone State & Badges
  let activeBusinessTimezone = 'America/New_York';

  const TIMEZONE_LABELS = {
    'America/New_York': 'Eastern Time (ET)',
    'America/Chicago': 'Central Time (CT)',
    'America/Denver': 'Mountain Time (MT)',
    'America/Phoenix': 'Mountain Time - AZ (MST)',
    'America/Los_Angeles': 'Pacific Time (PT)',
    'America/Anchorage': 'Alaska Time (AKT)',
    'Pacific/Honolulu': 'Hawaii Time (HST)',
    'UTC': 'UTC (UTC)'
  };

  function updateTimezoneBadges(tz) {
    const badgeTextEl = document.getElementById('business-tz-badge-text');
    if (badgeTextEl) {
      badgeTextEl.textContent = TIMEZONE_LABELS[tz] || tz;
    }
  }

  function setAppBusinessTimezone(tz) {
    if (!tz) return;
    activeBusinessTimezone = tz;
    updateTimezoneBadges(tz);
  }

  async function initBusinessTimezone() {
    try {
      const res = await fetch('/api/v1/portal/config');
      if (res.ok) {
        const cfg = await res.json();
        applyBusinessProfile(cfg);
        if (cfg && cfg.business_timezone) {
          setAppBusinessTimezone(cfg.business_timezone);
        }
      }
    } catch (e) {
      console.warn('Could not initialize business timezone from config:', e);
    }
  }


  let activeBusinessProfile = { industry: 'Service business', collect_vehicle_details: true, intake_fields: [] };
  function agentRole(value) {
    return String(value || 'Agent').replace(/technicians/gi, 'Agents').replace(/technician/gi, 'Agent');
  }
  function safeBusinessText(value) {
    const element = document.createElement('span');
    element.textContent = String(value ?? '');
    return element.innerHTML;
  }
  function applyBusinessProfile(config) {
    activeBusinessProfile = config.business_profile || activeBusinessProfile;
    const section = document.getElementById('sr-vehicle-section');
    if (section) {
      section.hidden = !activeBusinessProfile.collect_vehicle_details;
      section.querySelectorAll('input').forEach(input => {
        input.disabled = !activeBusinessProfile.collect_vehicle_details;
        input.required = activeBusinessProfile.collect_vehicle_details && input.id !== 'sr-veh-vin';
      });
    }
    ['new-service-req-vehicle-details', 'edit-service-req-vehicle-details'].forEach(id => {
      const checkbox = document.getElementById(id);
      if (checkbox) checkbox.closest('label').hidden = !activeBusinessProfile.collect_vehicle_details;
    });
  }
  function renderRequestIntake(values = {}) {
    const container = document.getElementById('sr-intake-fields');
    if (!container) return;
    container.replaceChildren();
    activeBusinessProfile.intake_fields.forEach(field => {
      const label = document.createElement('label');
      label.textContent = field.label + (field.required ? ' *' : '');
      const input = document.createElement('input');
      input.type = field.type === 'number' ? 'number' : 'text';
      if (field.type === 'number') input.step = 'any';
      input.className = 'form-input';
      input.dataset.intakeKey = field.key;
      input.required = field.required;
      if (field.type === 'text') input.maxLength = 2000;
      input.value = values[field.key] ?? '';
      label.appendChild(input);
      container.appendChild(label);
    });
    const configured = new Set(activeBusinessProfile.intake_fields.map(field => field.key));
    Object.entries(values).filter(([key]) => !configured.has(key)).forEach(([key, value]) => {
      const historical = document.createElement('p');
      historical.className = 'text-muted';
      historical.textContent = `${key.replaceAll('_', ' ')}: ${value} (previously collected)`;
      container.appendChild(historical);
    });
  }
  function collectRequestIntake() {
    const values = {};
    document.querySelectorAll('#sr-intake-fields [data-intake-key]').forEach(input => {
      if (input.value.trim()) values[input.dataset.intakeKey] = input.type === 'number' ? Number(input.value) : input.value;
    });
    return values;
  }
  function intakeDescription(request) {
    const fields = Object.fromEntries(activeBusinessProfile.intake_fields.map(field => [field.key, field.label]));
    const intake = Object.entries(request.intake_data || {}).map(([key, value]) => `${fields[key] || key.replaceAll('_', ' ')}: ${value}`).join('; ');
    const legacy = [request.year, request.make, request.model].filter(Boolean).join(' ');
    return safeBusinessText([legacy, intake].filter(Boolean).join(' · ') || '—');
  }
  function addBusinessIntakeRow(field = {}) {
    const row = document.createElement('div');
    row.className = 'business-intake-row form-group mt-4';
    row.dataset.key = field.key || '';
    row.style.cssText = 'display:flex;flex-direction:row;gap:12px;align-items:center;flex-wrap:wrap';
    row.innerHTML = '<label>Field label<input class="intake-label form-input" required maxlength="80"></label>' +
      '<label>Type<select class="intake-type form-input"><option value="text">Text</option><option value="number">Number</option></select></label>' +
      '<label class="checkbox-item"><input type="checkbox" class="intake-required">Required</label>' +
      '<button type="button" class="btn btn-secondary intake-remove">Remove</button>';
    row.querySelector('.intake-label').value = field.label || '';
    row.querySelector('.intake-type').value = field.type || 'text';
    row.querySelector('.intake-required').checked = !!field.required;
    row.querySelector('.intake-remove').addEventListener('click', () => row.remove());
    document.getElementById('business-intake-fields').appendChild(row);
  }
  async function loadBusinessProfile() {
    try {
      const response = await fetch('/api/v1/portal/config');
      if (!response.ok) throw new Error('Could not load business settings');
      const config = await response.json();
      applyBusinessProfile(config);
      document.getElementById('business-name').value = config.business_name || '';
      document.getElementById('business-portal-url').value = config.portal_base_url || '';
      document.getElementById('business-industry').value = activeBusinessProfile.industry;
      document.getElementById('business-collect-vehicle').checked = activeBusinessProfile.collect_vehicle_details;
      document.getElementById('business-regenerate-prompt').checked = false;
      document.getElementById('business-intake-fields').replaceChildren();
      activeBusinessProfile.intake_fields.forEach(addBusinessIntakeRow);
    } catch (error) { showToast(error.message, 'error'); }
  }
  document.getElementById('add-intake-field')?.addEventListener('click', () => {
    if (document.querySelectorAll('.business-intake-row').length >= 20) return showToast('Up to 20 intake fields are supported.', 'warning');
    addBusinessIntakeRow();
  });
  document.getElementById('business-profile-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const fields = Array.from(document.querySelectorAll('.business-intake-row')).map(row => {
        const label = row.querySelector('.intake-label').value.trim();
        const key = row.dataset.key || label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
        return { key, label, type: row.querySelector('.intake-type').value, required: row.querySelector('.intake-required').checked };
      });
      const response = await fetch('/api/v1/portal/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        business_name: document.getElementById('business-name').value.trim(),
        portal_base_url: document.getElementById('business-portal-url').value.trim(),
        business_profile: { industry: document.getElementById('business-industry').value.trim(), collect_vehicle_details: document.getElementById('business-collect-vehicle').checked, intake_fields: fields },
        regenerate_business_prompt: document.getElementById('business-regenerate-prompt').checked
      }) });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Check field labels and ensure each field has a unique name beginning with a letter.');
      }
      await loadBusinessProfile();
      showToast('Business settings saved.');
    } catch (error) { showToast(error.message, 'error'); }
    finally { button.disabled = false; }
  });

  // Elements
  const appContainer = document.querySelector('.app-container');
  const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
  const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');
  const navItems = document.querySelectorAll('.nav-item');
  const viewSections = document.querySelectorAll('.view-section');
  const viewTitle = document.getElementById('current-view-title');
  const refreshBtn = document.getElementById('refresh-data-btn');
  const toast = document.getElementById('app-toast');

  // Sidebar Toggle & Persistence (Responsive-aware)
  const sidebar = document.getElementById('app-sidebar');
  const mobileOverlay = document.getElementById('sidebar-mobile-overlay');

  function isMobileView() {
    return window.innerWidth <= 1024;
  }

  function updateSidebarButtonTitles() {
    const isHidden = appContainer && appContainer.classList.contains('sidebar-hidden');
    if (sidebarCollapseBtn) {
      sidebarCollapseBtn.setAttribute('title', isHidden ? 'Expand Sidebar' : 'Minimize Sidebar');
      sidebarCollapseBtn.setAttribute('aria-label', isHidden ? 'Expand Sidebar' : 'Minimize Sidebar');
    }
  }

  // On desktop: restore sidebar state from localStorage
  // On mobile: sidebar is always hidden by default (CSS handles this)
  if (!isMobileView()) {
    const isSidebarHidden = localStorage.getItem('sidebarHidden') === 'true';
    if (isSidebarHidden && appContainer) {
      appContainer.classList.add('sidebar-hidden');
    }
    updateSidebarButtonTitles();
  }

  function toggleSidebar() {
    if (!appContainer) return;

    if (isMobileView()) {
      // Mobile: toggle slide-in sidebar with overlay
      const isOpen = sidebar && sidebar.classList.contains('mobile-open');
      if (isOpen) {
        closeMobileSidebar();
      } else {
        openMobileSidebar();
      }
    } else {
      // Desktop: toggle sidebar-hidden class (minimized rail sidebar)
      appContainer.classList.toggle('sidebar-hidden');
      const isHidden = appContainer.classList.contains('sidebar-hidden');
      localStorage.setItem('sidebarHidden', isHidden ? 'true' : 'false');
      updateSidebarButtonTitles();
    }
  }

  function openMobileSidebar() {
    if (sidebar) sidebar.classList.add('mobile-open');
    if (mobileOverlay) mobileOverlay.classList.add('active');
    document.body.style.overflow = 'hidden'; // prevent scroll behind sidebar
  }

  function closeMobileSidebar() {
    if (sidebar) sidebar.classList.remove('mobile-open');
    if (mobileOverlay) mobileOverlay.classList.remove('active');
    document.body.style.overflow = '';
  }

  // Close mobile sidebar when clicking overlay
  if (mobileOverlay) {
    mobileOverlay.addEventListener('click', closeMobileSidebar);
  }

  // Close mobile sidebar when a nav item is clicked (navigates to a tab)
  navItems.forEach(item => {
    item.addEventListener('click', () => {
      if (isMobileView()) closeMobileSidebar();
    });
  });

  // Handle window resize: close mobile sidebar if resizing to desktop
  window.addEventListener('resize', () => {
    if (!isMobileView()) {
      closeMobileSidebar();
    }
  });

  if (sidebarToggleBtn) {
    sidebarToggleBtn.addEventListener('click', toggleSidebar);
  }
  if (sidebarCollapseBtn) {
    sidebarCollapseBtn.addEventListener('click', toggleSidebar);
  }
  
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
  const editAgentProfileBtn = document.getElementById('edit-agent-profile-btn');
  const editAgentDrawer = document.getElementById('edit-agent-drawer');
  const editAgentDrawerOverlay = document.getElementById('edit-agent-drawer-overlay');
  const closeEditAgentDrawerBtn = document.getElementById('close-edit-agent-drawer-btn');
  const cancelEditAgentBtn = document.getElementById('cancel-edit-agent-btn');
  const editAgentForm = document.getElementById('edit-agent-form');

  function openEditAgentDrawer() {
    if (editAgentDrawer) editAgentDrawer.classList.add('active');
    if (editAgentDrawerOverlay) editAgentDrawerOverlay.classList.add('active');
  }

  function closeEditAgentDrawer() {
    if (editAgentDrawer) editAgentDrawer.classList.remove('active');
    if (editAgentDrawerOverlay) editAgentDrawerOverlay.classList.remove('active');
  }

  if (closeEditAgentDrawerBtn) closeEditAgentDrawerBtn.addEventListener('click', closeEditAgentDrawer);
  if (cancelEditAgentBtn) cancelEditAgentBtn.addEventListener('click', closeEditAgentDrawer);
  if (editAgentDrawerOverlay) editAgentDrawerOverlay.addEventListener('click', closeEditAgentDrawer);
  
  // Document Drawer Elements
  const documentDrawer = document.getElementById('document-drawer');
  const documentDrawerOverlay = document.getElementById('document-drawer-overlay');
  const closeDocumentDrawerBtn = document.getElementById('close-document-drawer-btn');
  
  function closeDocumentDrawer() {
    documentDrawer.classList.remove('active');
    documentDrawerOverlay.classList.remove('active');
  }
  
  if (closeDocumentDrawerBtn) closeDocumentDrawerBtn.addEventListener('click', closeDocumentDrawer);
  if (documentDrawerOverlay) documentDrawerOverlay.addEventListener('click', closeDocumentDrawer);
  
  // Mapped View Titles & Subtitles
  const CONFIG_SUBTABS = ['business', 'staff', 'gmail', 'sms-config', 'customer-onboarding', 'intents', 'keys', 'analytics'];
  let activeConfigSubtab = 'staff';

  const TAB_METADATA = {
    'dashboard': {
      title: 'Dashboard Overview',
      subtitle: 'Real-time summaries, call metrics, and captured service request triage.'
    },
    'business': { title: 'Business & Intake', subtitle: 'Business identity and configurable customer intake fields.' },
    'config': {
      title: 'System Configuration',
      subtitle: 'Manage system settings, AI prompts, notifications, calendars, and API integrations.'
    },
    'analytics': {
      title: 'Operational Analytics & SLA Performance',
      subtitle: 'Real-time metrics on agent SLA compliance, escalation resolution, and staff response times.'
    },
    'intents': {
      title: 'AI Agent Config',
      subtitle: 'Configure ElevenLabs system prompt instructions, greetings, and AI persona.'
    },
    'services': {
      title: 'Services Catalog',
      subtitle: 'Service catalog database, duration, pricing, and required intake fields.'
    },
    'staff': {
      title: 'Staff Calendar Config',
      subtitle: 'Agent calendars, working shifts, slot availability, and Google Calendar sync.'
    },
    'knowledge': {
      title: 'Knowledge Base RAG',
      subtitle: 'Upload and index FAQ documents for real-time AI vector retrieval.'
    },
    'keys': {
      title: 'API Keys & Voice Settings',
      subtitle: 'Configure ElevenLabs voice IDs, LLM brains, and encrypted system API keys.'
    },
    'gmail': {
      title: 'Admin Config',
      subtitle: 'Configure admin booking email alerts, SMTP, and Google OAuth2 authorization.'
    },
    'sms-inbox': {
      title: 'Live SMS Inbox',
      subtitle: 'Real-time 2-way customer SMS dispatch, quick reply templates, and human handoff queue.'
    },
    'sms-config': {
      title: 'Notifications Config',
      subtitle: 'Global SMS support numbers, notification matrix rules, and test environment whitelist.'
    },
    'customer-onboarding': {
      title: 'Customer Config',
      subtitle: 'Onboard test customer numbers for Twilio WhatsApp message delivery and sandbox verification.'
    }
  };

  const viewSubtitle = document.getElementById('current-view-subtitle');

  function switchTab(tabName, updateHash = true) {
    let isConfig = false;
    let targetSubtab = null;

    if (tabName === 'config') {
      isConfig = true;
      targetSubtab = activeConfigSubtab || 'staff';
    } else if (CONFIG_SUBTABS.includes(tabName)) {
      isConfig = true;
      targetSubtab = tabName;
      activeConfigSubtab = tabName;
    } else if (!TAB_METADATA[tabName]) {
      tabName = 'dashboard';
    }

    if (isConfig) {
      // Update sidebar nav items state
      navItems.forEach(nav => {
        if (nav.getAttribute('data-tab') === 'config') {
          nav.classList.add('active');
        } else {
          nav.classList.remove('active');
        }
      });

      // Toggle views visibility - show config-view
      document.querySelectorAll('.view-section').forEach(section => {
        if (section.id === 'config-view') {
          section.classList.add('active');
        } else {
          section.classList.remove('active');
        }
      });

      // Update config ribbon items active state
      const ribbonItems = document.querySelectorAll('.config-ribbon-item');
      ribbonItems.forEach(item => {
        if (item.getAttribute('data-subtab') === targetSubtab) {
          item.classList.add('active');
        } else {
          item.classList.remove('active');
        }
      });

      // Update config subtab panes active state
      const subtabPanes = document.querySelectorAll('.config-subtab-pane');
      subtabPanes.forEach(pane => {
        if (pane.getAttribute('data-subtab-pane') === targetSubtab || pane.id === `${targetSubtab}-view`) {
          pane.classList.add('active');
        } else {
          pane.classList.remove('active');
        }
      });

      // Update title & subtitle header text
      const meta = TAB_METADATA[targetSubtab] || TAB_METADATA['config'];
      if (viewTitle) viewTitle.textContent = meta.title;
      if (viewSubtitle) viewSubtitle.textContent = meta.subtitle;

      // Update URL hash
      if (updateHash) {
        if (window.location.hash !== `#config/${targetSubtab}` && window.location.hash !== `#${targetSubtab}`) {
          window.history.pushState(null, '', `#config/${targetSubtab}`);
        }
      }

      // Trigger data loader for active subtab
      if (targetSubtab === 'business') {
        loadBusinessProfile();
      } else if (targetSubtab === 'staff') {
        loadStaffView();
      } else if (targetSubtab === 'gmail') {
        loadGmailConfig();
      } else if (targetSubtab === 'sms-config') {
        loadSMSConfig();
        loadSMSMatrixRules();
        loadSMSWhitelist();
      } else if (targetSubtab === 'customer-onboarding') {
        loadTwilioSandboxInfo();
        loadOnboardedTestCustomers();
      } else if (targetSubtab === 'intents') {
        loadConfigData();
      } else if (targetSubtab === 'keys') {
        loadVoiceData();
      } else if (targetSubtab === 'analytics') {
        loadAnalyticsView();
      }

    } else {
      // Main non-config tabs
      navItems.forEach(nav => {
        if (nav.getAttribute('data-tab') === tabName) {
          nav.classList.add('active');
        } else {
          nav.classList.remove('active');
        }
      });

      document.querySelectorAll('.view-section').forEach(section => {
        if (section.id === `${tabName}-view`) {
          section.classList.add('active');
        } else {
          section.classList.remove('active');
        }
      });

      const meta = TAB_METADATA[tabName];
      if (viewTitle) viewTitle.textContent = meta.title;
      if (viewSubtitle) viewSubtitle.textContent = meta.subtitle;

      if (updateHash && window.location.hash !== `#${tabName}`) {
        window.history.pushState(null, '', `#${tabName}`);
      }

      if (tabName === 'dashboard') {
        loadDashboardData();
      } else if (tabName === 'services') {
        loadServicesData();
      } else if (tabName === 'knowledge') {
        loadKBData();
      } else if (tabName === 'sms-inbox') {
        const filterEl = document.getElementById('sms-thread-filter');
        loadSMSConversations(filterEl ? filterEl.value : 'all');
      }
    }
  }

  window.handleUrlHash = function() {
    const rawHash = (window.location.hash || '').replace(/^#/, '').trim();
    if (rawHash.startsWith('config/')) {
      const sub = rawHash.split('/')[1];
      switchTab(sub || 'staff', false);
    } else if (rawHash && TAB_METADATA[rawHash]) {
      switchTab(rawHash, false);
    } else {
      switchTab('dashboard', false);
    }
  };

  // Tab Navigation Switching
  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const tabName = item.getAttribute('data-tab');
      switchTab(tabName, true);
    });
  });

  // Config Ribbon Navigation Switching
  const configRibbonItems = document.querySelectorAll('.config-ribbon-item');
  configRibbonItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const subtabName = item.getAttribute('data-subtab');
      switchTab(subtabName, true);
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
    let displayMsg = message;
    if (typeof message === 'object' && message !== null) {
      if (Array.isArray(message)) {
        displayMsg = message.map(item => item.msg || item.detail || JSON.stringify(item)).join('; ');
      } else {
        displayMsg = message.detail || message.message || JSON.stringify(message);
      }
    }
    toast.textContent = displayMsg;
    toast.className = 'toast active';
    if (type === 'error' || type === 'danger') {
      toast.style.borderColor = '#dc2626';
      toast.style.backgroundColor = '#1c1314';
      toast.style.color = '#fca5a5';
    } else if (type === 'warning') {
      toast.style.borderColor = '#d97706';
      toast.style.backgroundColor = '#1c1813';
      toast.style.color = '#fcd34d';
    } else {
      toast.style.borderColor = 'var(--border-card)';
      toast.style.backgroundColor = '#0c0d0e';
      toast.style.color = '#fff';
    }
    
    setTimeout(() => {
      toast.classList.remove('active');
    }, 4000);
  }

  // --- VIEW 1: DASHBOARD RETRIEVAL ---
  function formatLocalTimestamp(dateStr, options = {}) {
    if (!dateStr) return 'N/A';
    if (typeof dateStr !== 'string') dateStr = String(dateStr);

    let cleanStr = dateStr.trim();
    if (cleanStr.includes(' ') && !cleanStr.includes('T')) {
      cleanStr = cleanStr.replace(' ', 'T');
    }
    if (!cleanStr.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(cleanStr)) {
      cleanStr += 'Z';
    }

    const d = new Date(cleanStr);
    if (isNaN(d.getTime())) return dateStr;

    const tz = activeBusinessTimezone || 'America/New_York';

    if (options && options.timeOnly) {
      try {
        return new Intl.DateTimeFormat('en-US', {
          timeZone: tz,
          hour: '2-digit',
          minute: '2-digit',
          hour12: true
        }).format(d);
      } catch {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      }
    }

    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: tz,
        year: '2-digit',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true
      }).formatToParts(d);

      const map = {};
      parts.forEach(p => { map[p.type] = p.value; });
      return `${map.month}/${map.day}/${map.year} ${map.hour}:${map.minute} ${map.dayPeriod || ''}`.trim();
    } catch {
      const month = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const year = String(d.getFullYear()).slice(-2);

      let hours = d.getHours();
      const minutes = String(d.getMinutes()).padStart(2, '0');
      const ampm = hours >= 12 ? 'PM' : 'AM';
      hours = hours % 12 || 12;
      const hoursStr = String(hours).padStart(2, '0');

      return `${month}/${day}/${year} ${hoursStr}:${minutes} ${ampm}`;
    }
  }

  function formatShortDate(dateStr) {
    return formatLocalTimestamp(dateStr);
  }

  function formatBookingTimeRange(req) {
    if (req.booking_type === 'callback' && (!req.booking_time || req.booking_time.toUpperCase() === 'ASAP')) {
      return '<span class="badge danger">ASAP</span>';
    }

    const rawTime = req.booking_time || req.time_slot;
    if (!rawTime) {
      return '<span class="text-muted">N/A</span>';
    }

    function formatTime12(d) {
      if (isNaN(d.getTime())) return null;
      const tz = activeBusinessTimezone || 'America/New_York';
      try {
        return new Intl.DateTimeFormat('en-US', {
          timeZone: tz,
          hour: 'numeric',
          minute: '2-digit',
          hour12: true
        }).format(d);
      } catch {
        let hours = d.getHours();
        const minutes = String(d.getMinutes()).padStart(2, '0');
        const ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours : 12;
        return `${hours}:${minutes} ${ampm}`;
      }
    }

    function formatDateShort(d) {
      if (isNaN(d.getTime())) return null;
      const tz = activeBusinessTimezone || 'America/New_York';
      try {
        const parts = new Intl.DateTimeFormat('en-US', {
          timeZone: tz,
          year: '2-digit',
          month: '2-digit',
          day: '2-digit'
        }).formatToParts(d);
        const map = {};
        parts.forEach(p => { map[p.type] = p.value; });
        return `${map.month}/${map.day}/${map.year}`;
      } catch {
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        const year = String(d.getFullYear()).slice(-2);
        return `${month}/${day}/${year}`;
      }
    }

    const durationMin = req.duration_minutes || 60;
    let startDt = null;
    let endDt = null;

    if (req.booking_start_time) {
      const cleanStart = req.booking_start_time.includes(' ') && !req.booking_start_time.includes('T') ? req.booking_start_time.replace(' ', 'T') : req.booking_start_time;
      startDt = new Date(cleanStart);
    } else {
      const cleanRaw = String(rawTime).includes(' ') && !String(rawTime).includes('T') ? String(rawTime).replace(' ', 'T') : String(rawTime);
      startDt = new Date(cleanRaw);
    }

    if (req.booking_end_time) {
      const cleanEnd = req.booking_end_time.includes(' ') && !req.booking_end_time.includes('T') ? req.booking_end_time.replace(' ', 'T') : req.booking_end_time;
      endDt = new Date(cleanEnd);
    } else if (startDt && !isNaN(startDt.getTime())) {
      endDt = new Date(startDt.getTime() + durationMin * 60000);
    }

    if (startDt && !isNaN(startDt.getTime()) && endDt && !isNaN(endDt.getTime())) {
      const startDateStr = formatDateShort(startDt);
      const startTimeStr = formatTime12(startDt);
      const endDateStr = formatDateShort(endDt);
      const endTimeStr = formatTime12(endDt);

      const isSameDay = startDateStr === endDateStr;
      const rangeText = isSameDay 
        ? `${startTimeStr} – ${endTimeStr}`
        : `${startDateStr} ${startTimeStr} – ${endDateStr} ${endTimeStr}`;

      return `
        <div class="appointment-time-clean" style="display: flex; flex-direction: column; gap: 1px; white-space: nowrap;">
          <strong style="color: var(--text-main); font-size: 12px; font-weight: 600;">${startDateStr}</strong>
          <span style="color: var(--text-muted); font-size: 11.5px;">${rangeText}</span>
        </div>
      `;
    }

    return `<strong>${formatShortDate(rawTime)}</strong>`;
  }

  function formatPhoneNumber(phoneStr) {
    if (!phoneStr) return '--';
    const cleaned = ('' + phoneStr).replace(/\D/g, '');
    const match11 = cleaned.match(/^1?(\d{3})(\d{3})(\d{4})$/);
    if (match11) {
      return `(${match11[1]}) ${match11[2]}-${match11[3]}`;
    }
    return phoneStr;
  }

  async function updateAssignedAgent(requestId, staffAgentId) {
    try {
      const parsedId = staffAgentId ? parseInt(staffAgentId, 10) : null;
      const response = await fetch(`/api/v1/portal/service-requests/${requestId}/assign-agent`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ staff_agent_id: parsedId })
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to assign agent');
      }
      const data = await response.json().catch(() => ({}));
      const targetReq = allRequests.find(r => r.id === requestId);
      if (targetReq) {
        targetReq.staff_agent_id = parsedId;
        const updated = data.data || {};
        Object.assign(targetReq, updated);
        targetReq.status = updated.status || 'pending';
        targetReq.confirmation_status = updated.confirmation_status || 'pending_agent_confirmation';
        targetReq.confirmed_at = updated.confirmed_at || null;
      }
      showToast(`Agent reassigned for Service Request #${requestId}! Status set to pending for agent confirmation.`, 'success');
      applyServiceRequestsFilter();
    } catch (err) {
      showToast(err.message, 'danger');
      throw err;
    }
  }

  async function updateRequestStatus(requestId, newStatus) {
    try {
      const response = await fetch(`/api/v1/portal/service-requests/${requestId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to update request status');
      }
      const targetReq = allRequests.find(r => r.id === requestId);
      if (targetReq) {
        targetReq.status = newStatus === 'done' ? 'completed' : newStatus;
        if (['cancelled', 'cancelled_by_customer'].includes(targetReq.status)) {
          targetReq.escalation_status = 'none';
          targetReq.escalation_reason = null;
          targetReq.confirmation_status = 'cancelled';
        } else if (['completed', 'done'].includes(targetReq.status)) {
          if (targetReq.escalation_status === 'escalated') {
            targetReq.escalation_status = 'resolved';
          }
          targetReq.escalation_reason = null;
        }
      }
      const statusLabels = {
        completed: 'Done',
        done: 'Done',
        pending: 'Pending',
        confirmed: 'Confirmed',
        in_progress: 'In Progress',
        cancelled: 'Cancelled'
      };
      const label = statusLabels[newStatus] || newStatus;
      showToast(`Service Request #${requestId} marked as ${label}!`, 'success');
      applyServiceRequestsFilter();
      
      fetch('/api/v1/portal/stats')
        .then(res => res.ok ? res.json() : null)
        .then(stats => {
          if (stats) {
            const reqsStatEl = document.getElementById('stat-requests');
            if (reqsStatEl) reqsStatEl.textContent = stats.total_requests;
            const reqsBadgeEl = document.getElementById('stat-requests-badge');
            if (reqsBadgeEl && stats.pending_requests !== undefined) {
              const dotClass = stats.pending_requests === 0 ? 'success' : 'warning';
              reqsBadgeEl.innerHTML = `<span class="badge-dot ${dotClass}"></span>${stats.pending_requests} pending triage`;
              reqsBadgeEl.className = 'metric-badge';
            }
            const callbacksStatEl = document.getElementById('stat-callbacks');
            if (callbacksStatEl) callbacksStatEl.textContent = stats.total_callbacks;
            const apptsStatEl = document.getElementById('stat-appointments');
            if (apptsStatEl) apptsStatEl.textContent = stats.total_appointments;
          }
        }).catch(() => {});
      
      applyServiceRequestsFilter();
    } catch (err) {
      showToast(err.message, 'danger');
      throw err;
    }
  }

  function renderCallLogs(callsToRender) {
    const listBody = document.getElementById('call-logs-list');
    if (!listBody) return;
    
    const totalItems = callsToRender.length;
    const totalPages = Math.ceil(totalItems / callsPageSize) || 1;
    if (callsCurrentPage > totalPages) callsCurrentPage = totalPages;
    if (callsCurrentPage < 1) callsCurrentPage = 1;
    
    const startIndex = (callsCurrentPage - 1) * callsPageSize;
    const paginatedCalls = callsToRender.slice(startIndex, startIndex + callsPageSize);
    
    const infoEl = document.getElementById('calls-pagination-info');
    if (infoEl) {
      const endItem = Math.min(startIndex + callsPageSize, totalItems);
      infoEl.textContent = totalItems === 0 ? 'Showing 0 of 0 calls' : `Showing ${startIndex + 1}-${endItem} of ${totalItems} calls`;
    }
    const pageNumEl = document.getElementById('calls-page-num');
    if (pageNumEl) pageNumEl.textContent = `Page ${callsCurrentPage} of ${totalPages}`;
    
    const prevBtn = document.getElementById('calls-prev-page');
    if (prevBtn) prevBtn.disabled = callsCurrentPage <= 1;
    const nextBtn = document.getElementById('calls-next-page');
    if (nextBtn) nextBtn.disabled = callsCurrentPage >= totalPages;

    if (paginatedCalls.length === 0) {
      listBody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-muted">No matching call records found.</td></tr>`;
    } else {
      listBody.innerHTML = '';
      paginatedCalls.forEach(call => {
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

  function formatIssueDescription(rawDesc) {
    if (!rawDesc) return "";
    let desc = rawDesc;
    desc = desc.replace(/^(Appointment booked|Callback requested):\s*/i, '');
    desc = desc.replace(/\.?\s*Preferred time:.*$/i, '');
    desc = desc.replace(/\s*scheduled for.*$/i, '');
    desc = desc.replace(/\s*\(\d{4}\s+[a-zA-Z0-9\s-]+\)/g, '');
    desc = desc.replace(/\s+for\s+\d{4}\s+[a-zA-Z0-9\s-]+$/i, '');
    return desc.trim() || rawDesc;
  }

  function renderServiceRequests(requestsToRender) {
    const requestsListBody = document.getElementById('service-requests-list');
    if (!requestsListBody) return;
    
    const totalItems = requestsToRender.length;
    const totalPages = Math.ceil(totalItems / srPageSize) || 1;
    if (srCurrentPage > totalPages) srCurrentPage = totalPages;
    if (srCurrentPage < 1) srCurrentPage = 1;
    
    const startIndex = (srCurrentPage - 1) * srPageSize;
    const paginatedReqs = requestsToRender.slice(startIndex, startIndex + srPageSize);

    const infoEl = document.getElementById('sr-pagination-info');
    if (infoEl) {
      const endItem = Math.min(startIndex + srPageSize, totalItems);
      infoEl.textContent = totalItems === 0 ? 'Showing 0 of 0 requests' : `Showing ${startIndex + 1}-${endItem} of ${totalItems} requests`;
    }
    const pageNumEl = document.getElementById('sr-page-num');
    if (pageNumEl) pageNumEl.textContent = `Page ${srCurrentPage} of ${totalPages}`;
    
    const prevBtn = document.getElementById('sr-prev-page');
    if (prevBtn) prevBtn.disabled = srCurrentPage <= 1;
    const nextBtn = document.getElementById('sr-next-page');
    if (nextBtn) nextBtn.disabled = srCurrentPage >= totalPages;
    
    if (paginatedReqs.length === 0) {
      requestsListBody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-muted">No matching service requests found.</td></tr>`;
    } else {
      requestsListBody.innerHTML = '';
      paginatedReqs.forEach(req => {
        const tr = document.createElement('tr');
        
        const vehicleStr = intakeDescription(req);
        const baseDesc = formatIssueDescription(req.issue_description);
        const cleanDesc = req.booking_type === 'callback'
          ? `<span class="booking-type-tag callback">Callback</span>${baseDesc}`
          : baseDesc;
        
        let currentStatus = req.status;
        let statusBadgeClass = 'neutral';
        if (currentStatus === 'pending' || currentStatus === 'rescheduled') {
          statusBadgeClass = 'warning';
        } else if (currentStatus === 'cancelled' || currentStatus === 'cancelled_by_customer') {
          statusBadgeClass = 'danger';
        } else {
          statusBadgeClass = 'neutral';
        }

        let displayTime = formatBookingTimeRange(req);

        const isDone = ['completed', 'done', 'cancelled', 'cancelled_by_customer'].includes(currentStatus);

        let initialAgentName = req.staff_agent_name || 'Select Agent';
        let initialAgentRole = agentRole(req.staff_agent_role);
        if (!initialAgentRole && req.staff_agent_name && req.staff_agent_name.includes(' - ')) {
          const parts = req.staff_agent_name.split(' - ');
          initialAgentName = parts[0].trim();
          initialAgentRole = parts[1].trim();
        }
        if (!req.staff_agent_name) {
          initialAgentRole = 'Unassigned';
        }

        const waDisconnectedNotice = (req.staff_agent_id && req.staff_agent_whatsapp_connected === false)
          ? `<div style="font-size: 10px; color: #ef4444; margin-top: 2px;" title="Assigned agent has not connected WhatsApp. Outbound notification will fail delivery.">⚠️ WhatsApp Disconnected</div>`
          : '';

        const agentSelectHtml = `
          <div class="agent-badge-wrapper ${isDone ? 'disabled' : ''}">
            <div class="agent-badge-display">
              <div class="agent-name-line">${initialAgentName}</div>
              <div class="agent-role-line">${initialAgentRole}</div>
              ${waDisconnectedNotice}
            </div>
            <button type="button" class="agent-select-badge" data-id="${req.id}"
              aria-label="Change assigned agent" aria-haspopup="dialog"
              ${isDone ? 'disabled title="Agent cannot be changed for completed or cancelled tasks"' : ''}></button>
          </div>
        `;

        const isCancelled = ['cancelled', 'cancelled_by_customer'].includes(currentStatus);
        const isClosed = isCancelled || ['completed', 'done'].includes(currentStatus);
        let slaBadgeHtml = '';
        if (req.escalation_status === 'escalated' && !isClosed) {
          slaBadgeHtml = `<div class="sla-warning-badge overdue" style="background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4);" title="${req.escalation_reason || 'Escalated: Agent SLA Timeout'}"><span class="sla-dot" style="background: #ef4444;"></span> ⚠️ Escalated</div>`;
        } else if (req.escalation_status === 'reassigned' && !isClosed) {
          slaBadgeHtml = `<div class="sla-warning-badge" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3);"><span class="sla-dot" style="background: #60a5fa;"></span> Reassigned</div>`;
        } else if ((currentStatus === 'pending' || currentStatus === 'rescheduled') && !isClosed) {
          const slaStart = req.notification_dispatched_at || req.created_at;
          if (slaStart) {
            // Fix date parsing for Safari/cross-browser
            let safeDateStr = String(slaStart).replace(' ', 'T');
            if (!safeDateStr.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(safeDateStr)) safeDateStr += 'Z';
            
            const diffMs = Date.now() - new Date(safeDateStr).getTime();
            const diffMins = diffMs / 60000;
            if (diffMins > 60) {
              slaBadgeHtml = `<div class="sla-warning-badge overdue"><span class="sla-dot"></span> SLA Overdue</div>`;
            }

          }
        }

        const statusSelectHtml = `
          <div style="display: flex; flex-direction: column; align-items: flex-start;">
            <select class="status-select-badge ${statusBadgeClass}" data-id="${req.id}" data-status="${currentStatus}">
              <option value="pending" ${currentStatus === 'pending' || currentStatus === 'rescheduled' ? 'selected' : ''}>pending</option>
              <option value="confirmed" ${currentStatus === 'confirmed' ? 'selected' : ''}>confirmed</option>
              <option value="in_progress" ${currentStatus === 'in_progress' ? 'selected' : ''}>in progress</option>
              <option value="completed" ${currentStatus === 'completed' || currentStatus === 'done' ? 'selected' : ''}>done</option>
              <option value="cancelled" ${currentStatus === 'cancelled' || currentStatus === 'cancelled_by_customer' ? 'selected' : ''}>cancelled</option>
            </select>
            ${slaBadgeHtml}
          </div>
        `;

        const formattedPhone = formatPhoneNumber(req.phone);
        let failedLabel = '';
        if (req.has_failed_sms && req.has_failed_email) {
          failedLabel = '⚠️ Failed SMS & Email';
        } else if (req.has_failed_sms) {
          failedLabel = '⚠️ Failed SMS';
        } else if (req.has_failed_email) {
          failedLabel = '⚠️ Failed Email';
        }
        const failedIndicator = failedLabel ? `<span class="badge danger failed-sms-badge" title="Delivery failed">${failedLabel}</span>` : '';
        const reassignBtnHtml = (req.escalation_status === 'escalated' && !isClosed)
          ? `<button type="button" class="btn btn-primary btn-sm reassign-sr-btn" data-id="${req.id}" style="background: #ef4444; border-color: #ef4444; color: #fff;">Reassign</button>`
          : '';
        const actionsHtml = `
          <div class="actions-cell-container">
            ${failedIndicator}
            ${reassignBtnHtml}
            <button type="button" class="btn btn-secondary btn-sm edit-sr-btn" data-id="${req.id}">Edit</button>
            <button type="button" class="btn btn-secondary btn-sm details-sms-log-btn" data-id="${req.id}">Details</button>
          </div>
        `;

        tr.innerHTML = `
          <td><strong>${req.customer_name || 'Unknown Customer'}</strong></td>
          <td class="text-muted" style="font-size: 12.5px; white-space: nowrap;">${formattedPhone}</td>
          <td>${vehicleStr}</td>
          <td style="font-size: 12px; white-space: nowrap;">${displayTime}</td>
          <td>${agentSelectHtml}</td>
          <td>
            <div class="tooltip-container">
              <div class="issue-desc-text">${cleanDesc}</div>
              <div class="tooltip-popup">${cleanDesc}</div>
            </div>
          </td>
          <td style="text-align: center;">${statusSelectHtml}</td>
          <td style="text-align: center;">${actionsHtml}</td>
        `;

        const reassignBtn = tr.querySelector('.reassign-sr-btn');
        if (reassignBtn) {
          reassignBtn.addEventListener('click', () => {
            if (window.openReassignModal) window.openReassignModal(req);
          });
        }

        const detailsBtn = tr.querySelector('.details-sms-log-btn');
        if (detailsBtn) {
          detailsBtn.addEventListener('click', () => {
            if (window.openSMSLogDrawer) window.openSMSLogDrawer(req.id);
          });
        }

        const editBtn = tr.querySelector('.edit-sr-btn');
        if (editBtn) {
          editBtn.addEventListener('click', () => {
            if (window.openSREditModal) window.openSREditModal(req);
          });
        }

        const agentSelect = tr.querySelector('.agent-select-badge');
        if (agentSelect) {
          agentSelect.addEventListener('click', () => {
            if (!agentSelect.disabled) window.openReassignModal(req);
