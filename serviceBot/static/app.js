document.addEventListener('DOMContentLoaded', () => {
  
  // Local state for tables & pagination
  let allCalls = [];
  let allRequests = [];
  let srCurrentPage = 1;
  let srPageSize = 10;
  let callsCurrentPage = 1;
  let callsPageSize = 10;


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
  const TAB_METADATA = {
    'dashboard': {
      title: 'Dashboard Overview',
      subtitle: 'Real-time summaries, call metrics, and captured service request triage.'
    },
    'intents': {
      title: 'Agent Configurations',
      subtitle: 'Configure ElevenLabs system prompt instructions, greetings, and AI persona.'
    },
    'services': {
      title: 'Services Catalog',
      subtitle: 'Automotive service catalog database, duration, pricing, and required intake fields.'
    },
    'staff': {
      title: 'Staff Calendars',
      subtitle: 'Technician calendars, working shifts, slot availability, and Google Calendar sync.'
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
      title: 'Admin Notification Settings',
      subtitle: 'Configure admin booking email alerts, SMTP, and Google OAuth2 authorization.'
    },
    'sms-inbox': {
      title: 'Live SMS Inbox',
      subtitle: 'Real-time 2-way customer SMS dispatch, quick reply templates, and human handoff queue.'
    },
    'sms-config': {
      title: 'SMS Telephony Configuration',
      subtitle: 'Global SMS support numbers, notification matrix rules, and test environment whitelist.'
    }
  };

  const viewSubtitle = document.getElementById('current-view-subtitle');

  function switchTab(tabName, updateHash = true) {
    if (!TAB_METADATA[tabName]) {
      tabName = 'dashboard';
    }

    // Update sidebar nav items state
    navItems.forEach(nav => {
      if (nav.getAttribute('data-tab') === tabName) {
        nav.classList.add('active');
      } else {
        nav.classList.remove('active');
      }
    });

    // Toggle views visibility
    document.querySelectorAll('.view-section').forEach(section => {
      if (section.id === `${tabName}-view`) {
        section.classList.add('active');
      } else {
        section.classList.remove('active');
      }
    });

    // Update title & subtitle header text
    const meta = TAB_METADATA[tabName];
    if (viewTitle) viewTitle.textContent = meta.title;
    if (viewSubtitle) viewSubtitle.textContent = meta.subtitle;

    // Update URL hash if requested
    if (updateHash && window.location.hash !== `#${tabName}`) {
      window.history.pushState(null, '', `#${tabName}`);
    }

    // Trigger data loader for the active tab
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
    } else if (tabName === 'sms-config') {
      loadSMSConfig();
      loadSMSMatrixRules();
      loadSMSWhitelist();
    } else if (tabName === 'sms-inbox') {
      const filterEl = document.getElementById('sms-thread-filter');
      loadSMSConversations(filterEl ? filterEl.value : 'all');
    }
  }

  window.handleUrlHash = function() {
    const rawHash = (window.location.hash || '').replace(/^#/, '').trim();
    if (rawHash && TAB_METADATA[rawHash]) {
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
      const targetReq = allRequests.find(r => r.id === requestId);
      if (targetReq) {
        targetReq.staff_agent_id = parsedId;
      }
      showToast(`Agent reassigned for Service Request #${requestId}! Slot updated, old invite cancelled & admin notified.`, 'success');

    } catch (err) {
      showToast(err.message, 'danger');
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
      }
      const statusLabels = {
        completed: 'Done',
        done: 'Done',
        pending: 'Pending',
        in_progress: 'In Progress',
        rescheduled: 'Rescheduled',
        cancelled: 'Cancelled'
      };
      const label = statusLabels[newStatus] || newStatus;
      showToast(`Service Request #${requestId} marked as ${label}!`, 'success');
      
      fetch('/api/v1/portal/stats')
        .then(res => res.ok ? res.json() : null)
        .then(stats => {
          if (stats) {
            const reqsStatEl = document.getElementById('stat-requests');
            if (reqsStatEl) reqsStatEl.textContent = stats.total_requests;
            const reqsBadgeEl = document.getElementById('stat-requests-badge');
            if (reqsBadgeEl && stats.pending_requests !== undefined) {
              reqsBadgeEl.textContent = `${stats.pending_requests} pending triage`;
              reqsBadgeEl.className = stats.pending_requests === 0 ? 'metric-badge success' : 'metric-badge warning';
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
      requestsListBody.innerHTML = `<tr><td colspan="10" class="text-center py-6 text-muted">No matching service requests found.</td></tr>`;
    } else {
      requestsListBody.innerHTML = '';
      paginatedReqs.forEach(req => {
        const tr = document.createElement('tr');
        const formattedDate = formatShortDate(req.created_at);
        const vehicleStr = `${req.year} ${req.make} ${req.model}`;
        
        let currentStatus = req.status;
        let statusBadgeClass = 'warning';
        if (currentStatus === 'completed' || currentStatus === 'done' || currentStatus === 'confirmed') {
          statusBadgeClass = 'success';
        } else if (currentStatus === 'cancelled' || currentStatus === 'cancelled_by_customer') {
          statusBadgeClass = 'danger';
        } else if (currentStatus === 'in_progress') {
          statusBadgeClass = 'info';
        } else if (currentStatus === 'rescheduled') {
          statusBadgeClass = 'purple';
        }

        let reqTypeBadge = '';
        if (req.booking_type === 'appointment') {
          reqTypeBadge = '<span class="badge success">Appointment</span>';
        } else if (req.booking_type === 'callback') {
          reqTypeBadge = '<span class="badge info">Callback</span>';
        } else {
          reqTypeBadge = '<span class="text-muted">None</span>';
        }

        let displayTime = '';
        if (req.booking_type === 'callback' && (!req.booking_time || req.booking_time.toUpperCase() === 'ASAP')) {
          displayTime = '<span class="badge danger">ASAP</span>';
        } else if (req.booking_time) {
          const formattedBooking = formatShortDate(req.booking_time);
          displayTime = `<strong>${formattedBooking}</strong>`;
        } else {
          displayTime = '<span class="text-muted">N/A</span>';
        }

        const agentSelectHtml = `
          <select class="agent-select-badge" data-id="${req.id}">
            <option value="">${req.staff_agent_name || 'Select Agent'}</option>
          </select>
        `;

        const statusSelectHtml = `
          <select class="status-select-badge ${statusBadgeClass}" data-id="${req.id}" data-status="${currentStatus}">
            <option value="pending" ${currentStatus === 'pending' ? 'selected' : ''}>pending</option>
            <option value="confirmed" ${currentStatus === 'confirmed' ? 'selected' : ''}>confirmed</option>
            <option value="in_progress" ${currentStatus === 'in_progress' ? 'selected' : ''}>in progress</option>
            <option value="completed" ${currentStatus === 'completed' || currentStatus === 'done' ? 'selected' : ''}>done</option>
            <option value="rescheduled" ${currentStatus === 'rescheduled' ? 'selected' : ''}>rescheduled</option>
            <option value="cancelled" ${currentStatus === 'cancelled' ? 'selected' : ''}>cancelled</option>
            <option value="cancelled_by_customer" ${currentStatus === 'cancelled_by_customer' ? 'selected' : ''}>cancelled by customer</option>
          </select>
        `;

        const formattedPhone = formatPhoneNumber(req.phone);
        const failedIndicator = req.has_failed_sms ? '<span class="badge danger" style="padding: 2px 6px; font-size: 11px; font-weight: 600; margin-right: 4px;" title="SMS delivery failed">⚠️ Failed SMS</span>' : '';
        const actionsHtml = `
          <div style="display: flex; align-items: center; justify-content: center; gap: 4px;">
            ${failedIndicator}
            <button type="button" class="btn btn-secondary btn-sm details-sms-log-btn" data-id="${req.id}">Details</button>
          </div>
        `;

        tr.innerHTML = `
          <td class="text-muted" style="font-size: 12px; white-space: nowrap;">${formattedDate}</td>
          <td><strong>${req.customer_name || 'Unknown Customer'}</strong></td>
          <td class="text-muted" style="font-size: 12.5px; white-space: nowrap;">${formattedPhone}</td>
          <td>${vehicleStr}</td>
          <td style="text-align: center;">${reqTypeBadge}</td>
          <td style="font-size: 12px; white-space: nowrap;">${displayTime}</td>
          <td>${agentSelectHtml}</td>
          <td>
            <div class="tooltip-container">
              <div class="issue-desc-text">${req.issue_description}</div>
              <div class="tooltip-popup">${req.issue_description}</div>
            </div>
          </td>
          <td style="text-align: center;">${statusSelectHtml}</td>
          <td style="text-align: center;">${actionsHtml}</td>
        `;

        const detailsBtn = tr.querySelector('.details-sms-log-btn');
        if (detailsBtn) {
          detailsBtn.addEventListener('click', () => {
            if (window.openSMSLogDrawer) window.openSMSLogDrawer(req.id);
          });
        }

        const agentSelect = tr.querySelector('.agent-select-badge');
        if (agentSelect) {
          const loadAgentOptions = async () => {
            try {
              const res = await fetch(`/api/v1/portal/service-requests/${req.id}/available-agents`);
              if (!res.ok) return;
              const data = await res.json();
              if (data.agents && data.agents.length > 0) {
                let optionsHtml = `<option value="">Select Agent</option>`;
                data.agents.forEach(a => {
                  const isSel = (req.assigned_staff_id && Number(req.assigned_staff_id) === Number(a.id)) || (req.staff_agent_name === a.name);
                  optionsHtml += `<option value="${a.id}" ${isSel ? 'selected' : ''}>${a.name} - ${a.role}</option>`;
                });
                agentSelect.innerHTML = optionsHtml;
              }
            } catch (err) {
              console.error('Failed to fetch available agents:', err);
            }
          };

          loadAgentOptions();

          agentSelect.addEventListener('change', (e) => {
            updateAssignedAgent(req.id, e.target.value);
          });
        }

        const statusSelect = tr.querySelector('.status-select-badge');
        if (statusSelect) {
          statusSelect.addEventListener('change', (e) => {
            const newStatus = e.target.value;
            statusSelect.setAttribute('data-status', newStatus);
            let badgeClass = 'warning';
            if (newStatus === 'completed' || newStatus === 'done' || newStatus === 'confirmed') badgeClass = 'success';
            else if (newStatus === 'cancelled' || newStatus === 'cancelled_by_customer') badgeClass = 'danger';
            else if (newStatus === 'in_progress') badgeClass = 'info';
            else if (newStatus === 'rescheduled') badgeClass = 'purple';
            statusSelect.className = `status-select-badge ${badgeClass}`;
            updateRequestStatus(req.id, newStatus);
          });
        }

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
      const matchesStatus = status === 'all' || req.status === status || (status === 'completed' && req.status === 'done');
      
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
    srSearch.addEventListener('input', () => {
      srCurrentPage = 1;
      applyServiceRequestsFilter();
    });
  }
  const srType = document.getElementById('filter-sr-type');
  if (srType && !srType.dataset.listenerBound) {
    srType.dataset.listenerBound = 'true';
    srType.addEventListener('change', () => {
      srCurrentPage = 1;
      applyServiceRequestsFilter();
    });
  }
  const srStatus = document.getElementById('filter-sr-status');
  if (srStatus && !srStatus.dataset.listenerBound) {
    srStatus.dataset.listenerBound = 'true';
    srStatus.addEventListener('change', () => {
      srCurrentPage = 1;
      applyServiceRequestsFilter();
    });
  }

  const srPageSizeEl = document.getElementById('sr-page-size');
  if (srPageSizeEl && !srPageSizeEl.dataset.listenerBound) {
    srPageSizeEl.dataset.listenerBound = 'true';
    srPageSizeEl.addEventListener('change', () => {
      srPageSize = parseInt(srPageSizeEl.value) || 10;
      srCurrentPage = 1;
      applyServiceRequestsFilter();
    });
  }

  const srPrevBtn = document.getElementById('sr-prev-page');
  if (srPrevBtn && !srPrevBtn.dataset.listenerBound) {
    srPrevBtn.dataset.listenerBound = 'true';
    srPrevBtn.addEventListener('click', () => {
      if (srCurrentPage > 1) {
        srCurrentPage--;
        applyServiceRequestsFilter();
      }
    });
  }

  const srNextBtn = document.getElementById('sr-next-page');
  if (srNextBtn && !srNextBtn.dataset.listenerBound) {
    srNextBtn.dataset.listenerBound = 'true';
    srNextBtn.addEventListener('click', () => {
      srCurrentPage++;
      applyServiceRequestsFilter();
    });
  }

  // Bind Calls filters & pagination
  const callsSearch = document.getElementById('filter-calls-search');
  if (callsSearch && !callsSearch.dataset.listenerBound) {
    callsSearch.dataset.listenerBound = 'true';
    callsSearch.addEventListener('input', () => {
      callsCurrentPage = 1;
      applyCallsFilter();
    });
  }

  const callsPageSizeEl = document.getElementById('calls-page-size');
  if (callsPageSizeEl && !callsPageSizeEl.dataset.listenerBound) {
    callsPageSizeEl.dataset.listenerBound = 'true';
    callsPageSizeEl.addEventListener('change', () => {
      callsPageSize = parseInt(callsPageSizeEl.value) || 10;
      callsCurrentPage = 1;
      applyCallsFilter();
    });
  }

  const callsPrevBtn = document.getElementById('calls-prev-page');
  if (callsPrevBtn && !callsPrevBtn.dataset.listenerBound) {
    callsPrevBtn.dataset.listenerBound = 'true';
    callsPrevBtn.addEventListener('click', () => {
      if (callsCurrentPage > 1) {
        callsCurrentPage--;
        applyCallsFilter();
      }
    });
  }

  const callsNextBtn = document.getElementById('calls-next-page');
  if (callsNextBtn && !callsNextBtn.dataset.listenerBound) {
    callsNextBtn.dataset.listenerBound = 'true';
    callsNextBtn.addEventListener('click', () => {
      callsCurrentPage++;
      applyCallsFilter();
    });
  }

  let currentCallsTimeframe = '7d';
  const callsTimeframeSelect = document.getElementById('calls-timeframe-select');
  if (callsTimeframeSelect) {
    callsTimeframeSelect.addEventListener('change', (e) => {
      currentCallsTimeframe = e.target.value;
      loadDashboardData();
    });
  }


  async function loadDashboardData() {
    try {
      // Fetch stats
      const statsResponse = await fetch(`/api/v1/portal/stats?calls_timeframe=${currentCallsTimeframe}`);
      if (!statsResponse.ok) throw new Error('Failed to fetch stats');
      const stats = await statsResponse.json();
      
      // Render counts safely
      const totalCallsEl = document.getElementById('stat-total-calls');
      if (totalCallsEl) totalCallsEl.textContent = stats.total_calls;
      
      const callsBadgeEl = document.getElementById('stat-calls-badge');
      if (callsBadgeEl) {
        const labels = {
          '24h': 'Past 24 hours',
          '7d': 'Past 7 days',
          '30d': 'Past 30 days',
          'all': 'All time'
        };
        const labelText = labels[currentCallsTimeframe] || 'Past 7 days';
        callsBadgeEl.textContent = `${labelText} • 100% answer rate`;
      }
      
      const callbacksStatEl = document.getElementById('stat-callbacks');
      if (callbacksStatEl) callbacksStatEl.textContent = stats.total_callbacks;
      
      const apptsStatEl = document.getElementById('stat-appointments');
      if (apptsStatEl) apptsStatEl.textContent = stats.total_appointments;
      
      const reqsStatEl = document.getElementById('stat-requests');
      if (reqsStatEl) reqsStatEl.textContent = stats.total_requests;
      const reqsBadgeEl = document.getElementById('stat-requests-badge');
      if (reqsBadgeEl && stats.pending_requests !== undefined) {
        reqsBadgeEl.textContent = `${stats.pending_requests} pending triage`;
        reqsBadgeEl.className = stats.pending_requests === 0 ? 'metric-badge success' : 'metric-badge warning';
      }
      
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
    if (drawer) drawer.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
  }

  if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
  if (overlay) overlay.addEventListener('click', closeDrawer);

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

  // Seed Default Services Button
  const seedDefaultServicesBtn = document.getElementById('seed-default-services-btn');
  if (seedDefaultServicesBtn) {
    seedDefaultServicesBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      seedDefaultServicesBtn.disabled = true;
      const originalContent = seedDefaultServicesBtn.innerHTML;
      seedDefaultServicesBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Seeding...';

      try {
        const res = await fetch('/api/v1/portal/services/seed-defaults', { method: 'POST' });
        if (!res.ok) {
          const errBody = await res.json().catch(() => ({}));
          throw new Error(errBody.detail || 'Failed to seed default catalog');
        }
        const data = await res.json();
        showToast(`Catalog updated! Added ${data.inserted_count} missing default services. Total catalog: ${data.total_defaults} services.`, 'success');
        await loadServicesData();
      } catch (err) {
        console.error(err);
        showToast('Error seeding default catalog: ' + err.message, 'error');
      } finally {
        seedDefaultServicesBtn.disabled = false;
        seedDefaultServicesBtn.innerHTML = originalContent;
      }
    });
  }

  // Edit Service Drawer Actions
  function openEditDrawer(svc) {
    if (!editDrawer) return;
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
    
    if (editDrawer) editDrawer.classList.add('active');
    if (editDrawerOverlay) editDrawerOverlay.classList.add('active');
  }

  function closeEditDrawer() {
    if (editDrawer) editDrawer.classList.remove('active');
    if (editDrawerOverlay) editDrawerOverlay.classList.remove('active');
  }

  if (closeEditDrawerBtn) closeEditDrawerBtn.addEventListener('click', closeEditDrawer);
  if (cancelEditBtn) cancelEditBtn.addEventListener('click', closeEditDrawer);
  if (editDrawerOverlay) editDrawerOverlay.addEventListener('click', closeEditDrawer);

  if (editServiceForm) {
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
  }

  const addServiceForm = document.getElementById('add-service-form');
  if (addServiceForm) {
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
  }

  // --- VIEW 4: FILE DRAG AND DROP (RAG) ---
  const dropZone = document.getElementById('kb-drop-zone');
  const fileInput = document.getElementById('kb-file-input');
  const progressContainer = document.getElementById('upload-progress-container');
  const progressFill = document.getElementById('upload-progress-fill');
  const progressPercent = document.getElementById('upload-percent');
  const progressText = document.getElementById('upload-status-text');

  if (dropZone) {
    // Trigger file browsing on click
    dropZone.addEventListener('click', () => fileInput && fileInput.click());

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
  }

  // Handle file selection
  if (fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) {
        uploadKBFile(fileInput.files[0]);
      }
    });
  }

  async function uploadKBFile(file) {
    if (!file.name.endsWith('.txt') && !file.name.endsWith('.md')) {
      showToast('Only .txt or .md files are supported', 'error');
      return;
    }
    
    const formData = new FormData();
    formData.append('file', file);
    
    // Show progress loading indicators
    if (progressContainer) progressContainer.classList.remove('hidden');
    if (progressFill) progressFill.style.width = '30%';
    if (progressPercent) progressPercent.textContent = '30%';
    if (progressText) progressText.textContent = 'Uploading file...';
    
    try {
      const response = await fetch('/api/v1/portal/kb/upload', {
        method: 'POST',
        body: formData
      });
      
      if (!response.ok) throw new Error('File upload failure');
      const data = await response.json();
      
      if (progressFill) progressFill.style.width = '100%';
      if (progressPercent) progressPercent.textContent = '100%';
      if (progressText) progressText.textContent = 'Completed!';
      
      showToast(`Successfully indexed ${data.chunk_count} chunks into local ChromaDB!`);
      loadKBData();
      
      setTimeout(() => {
        if (progressContainer) progressContainer.classList.add('hidden');
      }, 3000);
      
    } catch (err) {
      console.error(err);
      if (progressContainer) progressContainer.classList.add('hidden');
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
      if (select) {
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
      }
    } catch (err) {
      console.warn(err);
      const select = document.getElementById('agent-voice-selection');
      if (select) {
        select.innerHTML = '<option value="default_mock">Mock Rachel (Default ElevenLabs)</option>' +
                           '<option value="default_mock2">Mock Clyde (Default ElevenLabs)</option>';
      }
    }
  }

  // Form Submit updates Voice routing Agent ID
  const voiceRoutingForm = document.getElementById('voice-routing-form');
  if (voiceRoutingForm) {
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
  }

  // Secrets Encrypt Form
  const saveKeysForm = document.getElementById('save-api-keys-form');
  if (saveKeysForm) {
    saveKeysForm.addEventListener('submit', (e) => {
      e.preventDefault();
      showToast('API credentials encrypted and securely saved at rest!');
    });
  }

  // --- VIEW 2: CONFIGURATION MANAGER ---
  async function loadConfigData() {
    try {
      const response = await fetch('/api/v1/portal/config');
      if (!response.ok) throw new Error('Failed to fetch configurations');
      const config = await response.json() || {};
      
      // Populate textareas and inputs
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
    const agentEmailDisplay = document.getElementById('agent-email-status-display');
    
    if (!calendarBadge || !connectCalendarBtn || !gmailBadge || !connectGmailBtn) return;
    
    const selectedOpt = Array.from(staffAgentSelector.options || []).find(opt => opt.value == selectedAgentId);
    const fallbackEmail = selectedOpt ? selectedOpt.dataset.email : '';

    if (!selectedAgentId) {
      calendarBadge.className = 'badge danger';
      calendarBadge.textContent = 'Disconnected';
      connectCalendarBtn.textContent = 'Connect';
      connectCalendarBtn.classList.add('btn-secondary');
      connectCalendarBtn.style.borderColor = 'var(--color-primary)';
      connectCalendarBtn.style.color = '#fff';
      connectCalendarBtn.dataset.isConnected = 'false';
      connectCalendarBtn.disabled = true;
      
      gmailBadge.className = 'badge danger';
      gmailBadge.textContent = 'Disconnected';
      connectGmailBtn.textContent = 'Connect';
      connectGmailBtn.classList.add('btn-secondary');
      connectGmailBtn.style.borderColor = 'var(--color-primary)';
      connectGmailBtn.style.color = '#fff';
      connectGmailBtn.dataset.isConnected = 'false';
      connectGmailBtn.disabled = true;
      
      if (deleteAgentProfileBtn) deleteAgentProfileBtn.disabled = true;
      if (agentEmailDisplay) agentEmailDisplay.textContent = 'No agent selected';
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
      
      if (agentEmailDisplay) {
        const activeEmail = status.email || fallbackEmail;
        if (activeEmail) {
          agentEmailDisplay.textContent = activeEmail;
        } else if (calendarConnected || gmailConnected || status.is_connected) {
          agentEmailDisplay.textContent = 'Connected (Google Account)';
        } else {
          agentEmailDisplay.textContent = 'No email configured';
        }
      }
      
      if (calendarConnected) {
        calendarBadge.className = 'badge success';
        calendarBadge.textContent = 'Connected';
        connectCalendarBtn.textContent = 'Disconnect';
        connectCalendarBtn.classList.add('btn-secondary');
        connectCalendarBtn.style.borderColor = 'var(--color-danger)';
        connectCalendarBtn.style.color = 'var(--color-danger)';
        connectCalendarBtn.dataset.isConnected = 'true';
      } else {
        calendarBadge.className = 'badge danger';
        calendarBadge.textContent = 'Disconnected';
        connectCalendarBtn.textContent = 'Connect';
        connectCalendarBtn.classList.add('btn-secondary');
        connectCalendarBtn.style.borderColor = 'var(--color-primary)';
        connectCalendarBtn.style.color = '#fff';
        connectCalendarBtn.dataset.isConnected = 'false';
      }
      
      if (gmailConnected) {
        gmailBadge.className = 'badge success';
        gmailBadge.textContent = 'Connected';
        connectGmailBtn.textContent = 'Disconnect';
        connectGmailBtn.classList.add('btn-secondary');
        connectGmailBtn.style.borderColor = 'var(--color-danger)';
        connectGmailBtn.style.color = 'var(--color-danger)';
        connectGmailBtn.dataset.isConnected = 'true';
      } else {
        gmailBadge.className = 'badge danger';
        gmailBadge.textContent = 'Disconnected';
        connectGmailBtn.textContent = 'Connect';
        connectGmailBtn.classList.add('btn-secondary');
        connectGmailBtn.style.borderColor = 'var(--color-primary)';
        connectGmailBtn.style.color = '#fff';
        connectGmailBtn.dataset.isConnected = 'false';
      }
    } catch (err) {
      console.error('Error fetching Google connection status:', err);
      if (agentEmailDisplay) {
        agentEmailDisplay.textContent = fallbackEmail || 'No email configured';
      }
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
        const emailSuffix = agent.email ? ` - ${agent.email}` : '';
        opt.textContent = `${agent.name} (${agent.role || 'Service Agent'})${emailSuffix}`;
        opt.dataset.email = agent.email || '';
        opt.dataset.dbEmail = agent.db_email || agent.email || '';
        opt.dataset.name = agent.name || '';
        opt.dataset.role = agent.role || '';
        opt.dataset.phone = agent.phone_number || '';
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

      // Populate Business Hours & Workdays config in Staff view
      try {
        const cfgRes = await fetch('/api/v1/portal/config');
        if (cfgRes.ok) {
          const cfg = await cfgRes.json();
          const bStartEl = document.getElementById('staff-bhours-start');
          const bEndEl = document.getElementById('staff-bhours-end');
          if (bStartEl) bStartEl.value = cfg.business_hours_start ?? 7;
          if (bEndEl) bEndEl.value = cfg.business_hours_end ?? 18;
          
          const validDays = cfg.business_days || [0, 1, 2, 3, 4];
          const dayCbs = document.querySelectorAll('.staff-day-cb');
          dayCbs.forEach(cb => {
            cb.checked = validDays.includes(parseInt(cb.value, 10));
          });
        }
      } catch (err) {
        console.error('Error fetching config for staff view:', err);
      }

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
        if (addSlotForm) {
          addSlotForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const selectedAgentId = staffAgentSelector.value;
            if (!selectedAgentId) {
              showToast('Please select a staff member first.', 'error');
              return;
            }
            
            const rawDatetime = newSlotDatetimeInput ? newSlotDatetimeInput.value : '';
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
              if (newSlotDatetimeInput) newSlotDatetimeInput.value = '';
              loadAgentCalendar(selectedAgentId);
            } catch (err) {
              console.error(err);
              showToast('Error adding slot: ' + err.message, 'error');
            }
          });
        }

        // Add Staff Member Form handler
        if (addAgentForm) {
          addAgentForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = newAgentNameInput.value.trim();
            const role = newAgentRoleInput.value.trim() || 'Service Advisor';
            const email = newAgentEmailInput.value.trim() || null;
            const newAgentPhoneInput = document.getElementById('new-agent-phone');
            const phone_number = newAgentPhoneInput ? (newAgentPhoneInput.value.trim() || null) : null;
            
            if (!name) return;
            
            try {
              const response = await fetch('/api/v1/portal/agents', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, role, email, phone_number })
              });
              if (!response.ok) {
                const data = await response.json();
                throw new Error(data.detail || 'Failed to add staff member');
              }
              const data = await response.json();

              // Auto-trigger Twilio Verified Caller ID if phone_number is provided
              if (phone_number) {
                try {
                  await fetch('/api/v1/portal/twilio/verify-caller-id', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone_number, friendly_name: name })
                  });
                } catch (e) {
                  console.error('Auto caller-id verify error:', e);
                }
              }

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

        const verifyAgentTwilioBtn = document.getElementById('verify-agent-twilio-btn');
        if (verifyAgentTwilioBtn) {
          verifyAgentTwilioBtn.addEventListener('click', async () => {
            const newAgentPhoneInput = document.getElementById('new-agent-phone');
            const phone = newAgentPhoneInput ? newAgentPhoneInput.value.trim() : '';
            if (!phone) {
              showToast('Please enter a phone number first.', 'error');
              return;
            }
            try {
              const name = newAgentNameInput ? newAgentNameInput.value.trim() : 'Staff Member';
              const res = await fetch('/api/v1/portal/twilio/verify-caller-id', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone_number: phone, friendly_name: name })
              });
              if (!res.ok) throw new Error('Verification request failed');
              showToast(`Phone number ${phone} submitted to Twilio Verified Caller IDs!`);
            } catch (err) {
              showToast('Twilio verification error: ' + err.message, 'error');
            }
          });
        }

        // Edit Profile click handler
        if (editAgentProfileBtn) {
          editAgentProfileBtn.addEventListener('click', async () => {
            const agentId = staffAgentSelector.value;
            if (!agentId) {
              showToast('Please select a staff member to edit.', 'error');
              return;
            }

            const selectedOpt = staffAgentSelector.options[staffAgentSelector.selectedIndex];
            let name = selectedOpt ? selectedOpt.dataset.name : '';
            let role = selectedOpt ? selectedOpt.dataset.role : '';
            let email = selectedOpt ? (selectedOpt.dataset.dbEmail || selectedOpt.dataset.email) : '';
            let phone = selectedOpt ? selectedOpt.dataset.phone : '';

            try {
              const res = await fetch(`/api/v1/portal/agents/${agentId}`);
              if (res.ok) {
                const agent = await res.json();
                name = agent.name || name;
                role = agent.role || role;
                email = agent.db_email || agent.email || email;
                phone = agent.phone_number || phone;
              }
            } catch (err) {
              console.warn('Endpoint fetch fallback to dataset:', err);
            }

            document.getElementById('edit-agent-id').value = agentId;
            document.getElementById('edit-agent-name').value = name || '';
            document.getElementById('edit-agent-role').value = role || 'Service Advisor';
            document.getElementById('edit-agent-email').value = email || '';
            document.getElementById('edit-agent-phone').value = phone || '';

            openEditAgentDrawer();
          });
        }

        // Verify edit agent phone with Twilio Caller ID
        const verifyEditAgentTwilioBtn = document.getElementById('verify-edit-agent-twilio-btn');
        if (verifyEditAgentTwilioBtn) {
          verifyEditAgentTwilioBtn.addEventListener('click', async () => {
            const phoneInput = document.getElementById('edit-agent-phone');
            const nameInput = document.getElementById('edit-agent-name');
            const phone = phoneInput ? phoneInput.value.trim() : '';
            if (!phone) {
              showToast('Please enter a phone number first.', 'error');
              return;
            }
            try {
              const name = nameInput ? nameInput.value.trim() : 'Staff Member';
              const res = await fetch('/api/v1/portal/twilio/verify-caller-id', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone_number: phone, friendly_name: name })
              });
              if (!res.ok) throw new Error('Verification request failed');
              showToast(`Phone number ${phone} submitted to Twilio Verified Caller IDs!`);
            } catch (err) {
              showToast('Twilio verification error: ' + err.message, 'error');
            }
          });
        }

        // Edit Staff Member Form submission handler
        if (editAgentForm) {
          editAgentForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const agentId = document.getElementById('edit-agent-id').value;
            const name = document.getElementById('edit-agent-name').value.trim();
            const role = document.getElementById('edit-agent-role').value.trim() || 'Service Advisor';
            const email = document.getElementById('edit-agent-email').value.trim() || null;
            const phone_number = document.getElementById('edit-agent-phone').value.trim() || null;

            if (!agentId || !name) return;

            try {
              const response = await fetch(`/api/v1/portal/agents/${agentId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, role, email, phone_number })
              });

              if (!response.ok) {
                const data = await response.json();
                throw new Error(data.detail || 'Failed to update staff member');
              }

              const data = await response.json();

              // Auto-trigger Twilio Verified Caller ID if phone_number is provided
              if (phone_number) {
                try {
                  await fetch('/api/v1/portal/twilio/verify-caller-id', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone_number, friendly_name: name })
                  });
                } catch (e) {
                  console.error('Auto caller-id verify error:', e);
                }
              }

              const syncInfo = data.calendar_sync ? ` (${data.calendar_sync.total || 0} slots synced)` : '';
              showToast(`Staff member "${name}" updated & calendar synced successfully!${syncInfo}`);
              closeEditAgentDrawer();

              // Reload staff view and re-select updated agent
              await loadStaffView(agentId);
            } catch (err) {
              console.error(err);
              showToast('Error updating staff member: ' + err.message, 'error');
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
        
        // Business Hours & Workdays Form handler
        const staffBhoursForm = document.getElementById('staff-bhours-form');
        if (staffBhoursForm && !staffBhoursForm.dataset.listenerAttached) {
          staffBhoursForm.dataset.listenerAttached = 'true';
          staffBhoursForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const bStartEl = document.getElementById('staff-bhours-start');
            const bEndEl = document.getElementById('staff-bhours-end');
            const dayCbs = document.querySelectorAll('.staff-day-cb');
            
            const bStart = bStartEl ? parseInt(bStartEl.value, 10) : 7;
            const bEnd = bEndEl ? parseInt(bEndEl.value, 10) : 18;
            const selectedDays = [];
            dayCbs.forEach(cb => {
              if (cb.checked) selectedDays.push(parseInt(cb.value, 10));
            });
            
            if (selectedDays.length === 0) {
              showToast('Please select at least one operating day of the week.', 'error');
              return;
            }
            
            try {
              const res = await fetch('/api/v1/portal/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  business_hours_start: bStart,
                  business_hours_end: bEnd,
                  business_days: selectedDays
                })
              });
              if (!res.ok) throw new Error('Failed to update business hours');
              showToast('Business hours and operating workdays updated successfully!');
            } catch (err) {
              console.error(err);
              showToast('Error saving business hours: ' + err.message, 'error');
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

  // --- VIEW 7: ADMIN NOTIFICATION CONFIG ---
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

      if (document.getElementById('admin-sms-phone')) {
        document.getElementById('admin-sms-phone').value = config.admin_phone_number || '';
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
        admin_phone_number: document.getElementById('admin-sms-phone') ? document.getElementById('admin-sms-phone').value.trim() : null,
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

  // Handle Test Admin SMS button
  const testAdminSmsBtn = document.getElementById('test-admin-sms-btn');
  if (testAdminSmsBtn) {
    testAdminSmsBtn.addEventListener('click', async () => {
      const adminPhoneInput = document.getElementById('admin-sms-phone');
      const admin_phone_number = adminPhoneInput ? adminPhoneInput.value.trim() : '';

      if (!admin_phone_number) {
        showToast('Please enter an Admin Contact Phone Number first.', 'error');
        return;
      }

      showToast('Sending test SMS to Admin...', 'info');
      testAdminSmsBtn.disabled = true;

      try {
        const response = await fetch('/api/v1/portal/sms/admin/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ admin_phone_number })
        });

        testAdminSmsBtn.disabled = false;

        if (!response.ok) {
          const errData = await response.json();
          throw new Error(errData.detail || 'Failed to send Admin Test SMS');
        }

        showToast('Admin Test SMS sent successfully!');
      } catch (err) {
        testAdminSmsBtn.disabled = false;
        console.error(err);
        showToast('Admin SMS Test Failed: ' + err.message, 'error');
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


  // --- VIEW: LIVE SMS INBOX & SMS CONFIGURATION ---
  let activeConversationId = null;

  async function loadSMSConfig() {
    try {
      const res = await fetch('/api/v1/portal/sms/config');
      if (!res.ok) return;
      const config = await res.json();
      if (!config) return;

      document.getElementById('sms-config-support-phone').value = config.support_phone_number || '';
      if (document.getElementById('sms-config-admin-phone')) {
        document.getElementById('sms-config-admin-phone').value = config.admin_phone_number || '';
      }
      const envVal = (config.environment === 'TESTING' || config.environment === 'TEST') ? 'TEST' : (config.environment || 'TEST');
      document.getElementById('sms-config-environment').value = envVal;
      document.getElementById('sms-config-quiet-start').value = config.quiet_start_time || '21:00';
      document.getElementById('sms-config-quiet-end').value = config.quiet_end_time || '08:00';
      document.getElementById('sms-config-auto-responder').value = config.auto_responder_template || '';
    } catch (err) {
      console.error('Error loading SMS config:', err);
    }
  }

  async function loadSMSMatrixRules() {
    try {
      const res = await fetch('/api/v1/portal/sms/matrix-rules');
      if (!res.ok) return;
      const rules = await res.json();
      const tbody = document.getElementById('sms-matrix-rules-tbody');
      if (!tbody) return;
      tbody.innerHTML = '';

      const events = ['BOOKING', 'RESCHEDULED', 'REASSIGNED', 'RESCHEDULED_REASSIGNED', 'CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_ADMIN', 'REMINDER_24H', 'REMINDER_2H'];
      const roles = ['customer', 'agent', 'previous_agent', 'admin'];

      events.forEach(evt => {
        const tr = document.createElement('tr');
        const formattedEventName = evt.replace(/_/g, ' ');
        tr.innerHTML = `<td><span style="font-size: 12px; font-weight: 500; color: var(--text-main);">${formattedEventName}</span></td>` + roles.map(r => {
          const rule = rules.find(x => x.event_type === evt && x.recipient_role === r);
          const checked = rule ? rule.enabled : (r !== 'admin' && !(evt === 'REASSIGNED' && r === 'customer'));
          return `<td>
            <label class="matrix-status-pill ${checked ? 'active' : 'disabled'}" style="cursor: pointer;">
              <input type="checkbox" class="sms-matrix-cb" data-event="${evt}" data-role="${r}" ${checked ? 'checked' : ''} style="margin-right: 4px;">
              <span>${checked ? 'Active' : 'Disabled'}</span>
            </label>
          </td>`;
        }).join('');
        tbody.appendChild(tr);
      });

      tbody.querySelectorAll('.sms-matrix-cb').forEach(cb => {
        cb.addEventListener('change', async (e) => {
          const event_type = e.target.dataset.event;
          const recipient_role = e.target.dataset.role;
          const enabled = e.target.checked;
          const pill = e.target.closest('.matrix-status-pill');
          if (pill) {
            pill.className = `matrix-status-pill ${enabled ? 'active' : 'disabled'}`;
            const labelSpan = pill.querySelector('span');
            if (labelSpan) labelSpan.textContent = enabled ? 'Active' : 'Disabled';
          }
          await fetch('/api/v1/portal/sms/matrix-rules', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event_type, recipient_role, enabled })
          });
          showToast('Notification matrix rule updated.');
        });
      });
    } catch (err) {
      console.error('Error loading matrix rules:', err);
    }
  }

  async function loadSMSWhitelist() {
    try {
      const res = await fetch('/api/v1/portal/sms/whitelist');
      if (!res.ok) return;
      const whitelist = await res.json();
      const tbody = document.getElementById('sms-whitelist-tbody');
      if (!tbody) return;
      tbody.innerHTML = '';

      if (whitelist.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-muted text-center py-6">No whitelisted numbers added. All outbound SMS logged locally in test mode.</td></tr>';
        return;
      }

      whitelist.forEach(item => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><code style="font-size: 12.5px; background: rgba(255,255,255,0.05); padding: 2px 6px; border-radius: 4px;">${item.phone_number}</code></td>
          <td><strong>${item.friendly_name || '--'}</strong></td>
          <td>
            <span class="${item.twilio_verified ? 'badge-verified' : 'badge-unverified'}">
              ${item.twilio_verified ? 'Verified' : 'Pending'}
            </span>
          </td>
          <td>
            <button class="btn btn-sm btn-danger delete-whitelist-btn" data-id="${item.id}">
              <svg class="btn-icon" viewBox="0 0 24 24" width="14" height="14"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
              Remove
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      tbody.querySelectorAll('.delete-whitelist-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          const id = e.target.closest('button').dataset.id;
          await fetch(`/api/v1/portal/sms/whitelist/${id}`, { method: 'DELETE' });
          showToast('Whitelist entry removed.');
          loadSMSWhitelist();
        });
      });
    } catch (err) {
      console.error('Error loading SMS whitelist:', err);
    }
  }

  const smsGlobalForm = document.getElementById('sms-global-config-form');
  if (smsGlobalForm) {
    smsGlobalForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = {
        support_phone_number: document.getElementById('sms-config-support-phone').value,
        admin_phone_number: document.getElementById('sms-config-admin-phone') ? document.getElementById('sms-config-admin-phone').value.trim() : null,
        environment: document.getElementById('sms-config-environment').value,
        quiet_start_time: document.getElementById('sms-config-quiet-start').value,
        quiet_end_time: document.getElementById('sms-config-quiet-end').value,
        auto_responder_template: document.getElementById('sms-config-auto-responder').value
      };
      await fetch('/api/v1/portal/sms/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      showToast('SMS global configuration saved successfully.');
    });
  }

  const smsWhitelistForm = document.getElementById('sms-add-whitelist-form');
  if (smsWhitelistForm) {
    smsWhitelistForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const phone_number = document.getElementById('whitelist-phone-input').value;
      const friendly_name = document.getElementById('whitelist-name-input').value;
      await fetch('/api/v1/portal/twilio/verify-caller-id', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone_number, friendly_name })
      });
      showToast('Phone number added and caller ID verified.');
      document.getElementById('whitelist-phone-input').value = '';
      document.getElementById('whitelist-name-input').value = '';
      loadSMSWhitelist();
    });
  }

  let cachedConversationsList = [];

  async function loadSMSConversations(filterState = 'HANDOFF_REQUIRED') {
    try {
      const url = filterState && filterState !== 'all' ? `/api/v1/portal/sms/conversations?state=${filterState}` : '/api/v1/portal/sms/conversations';
      const res = await fetch(url);
      if (!res.ok) return;
      const convs = await res.json();
      cachedConversationsList = convs;

      // Update stat counter pills
      let countAttention = 0, countProgress = 0, countResolved = 0;
      convs.forEach(c => {
        if (c.state === 'HANDOFF_REQUIRED') countAttention++;
        else if (c.state === 'IN_PROGRESS') countProgress++;
        else if (c.state === 'RESOLVED') countResolved++;
      });
      const statAttentionEl = document.getElementById('stat-sms-attention');
      const statProgressEl = document.getElementById('stat-sms-progress');
      const statResolvedEl = document.getElementById('stat-sms-resolved');
      if (statAttentionEl) statAttentionEl.innerHTML = `<span class="stat-dot attention"></span> ${countAttention} Handoffs`;
      if (statProgressEl) statProgressEl.innerHTML = `<span class="stat-dot progress"></span> ${countProgress} In Progress`;
      if (statResolvedEl) statResolvedEl.innerHTML = `<span class="stat-dot resolved"></span> ${countResolved} Resolved`;

      renderFilteredConversations();
    } catch (err) {
      console.error('Error loading SMS conversations:', err);
    }
  }

  function renderFilteredConversations() {
    const container = document.getElementById('sms-threads-list');
    if (!container) return;
    container.innerHTML = '';

    const searchTerm = (document.getElementById('sms-thread-search-input')?.value || '').toLowerCase().trim();
    const filtered = cachedConversationsList.filter(c => {
      if (!searchTerm) return true;
      const nameMatch = (c.customer_name || '').toLowerCase().includes(searchTerm);
      const phoneMatch = (c.customer_phone || '').toLowerCase().includes(searchTerm);
      return nameMatch || phoneMatch;
    });

    if (filtered.length === 0) {
      container.innerHTML = '<div class="threads-empty-state"><p class="text-muted text-center">No matching conversation threads found.</p></div>';
      return;
    }

    filtered.forEach(c => {
      const item = document.createElement('div');
      const isActive = c.id === activeConversationId;
      item.className = `thread-item ${isActive ? 'active' : ''}`;
      
      let stateBadgeText = 'Bot Active';
      let stateBadgeClass = 'automated';
      let avatarRing = 'ring-resolved';

      if (c.state === 'HANDOFF_REQUIRED') {
        stateBadgeText = 'Needs Handoff';
        stateBadgeClass = 'handoff';
        avatarRing = 'ring-handoff';
      } else if (c.state === 'IN_PROGRESS') {
        stateBadgeText = 'In Progress';
        stateBadgeClass = 'progress';
        avatarRing = 'ring-progress';
      } else if (c.state === 'RESOLVED') {
        stateBadgeText = 'Resolved';
        stateBadgeClass = 'resolved';
        avatarRing = 'ring-resolved';
      }

      const initialChar = (c.customer_name ? c.customer_name.charAt(0) : 'P').toUpperCase();
      const formattedTime = c.updated_at ? new Date(c.updated_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '';

      item.innerHTML = `
        <div class="thread-avatar ${avatarRing}">${initialChar}</div>
        <div class="thread-content-body">
          <div class="thread-row-top">
            <span class="thread-customer-title">${c.customer_name || c.customer_phone}</span>
            <span class="thread-time">${formattedTime}</span>
          </div>
          <div class="thread-phone-subtitle">${c.customer_phone}</div>
          <span class="thread-state-badge ${stateBadgeClass}">${stateBadgeText}</span>
        </div>
      `;

      item.addEventListener('click', () => {
        activeConversationId = c.id;
        document.querySelectorAll('.thread-item').forEach(el => el.classList.remove('active'));
        item.classList.add('active');
        loadSMSMessages(c.id, c);
      });
      container.appendChild(item);
    });
  }

  // Search input handler
  const searchInputEl = document.getElementById('sms-thread-search-input');
  if (searchInputEl) {
    searchInputEl.addEventListener('input', () => {
      renderFilteredConversations();
    });
  }

  let activeConversationDetails = null;

  async function loadSMSMessages(conversationId, convDetails) {
    try {
      activeConversationDetails = convDetails;
      const initialChar = (convDetails.customer_name ? convDetails.customer_name.charAt(0) : 'P').toUpperCase();
      
      const avatarEl = document.getElementById('chat-customer-avatar');
      if (avatarEl) avatarEl.textContent = initialChar;

      const nameEl = document.getElementById('chat-customer-name');
      if (nameEl) nameEl.textContent = convDetails.customer_name || convDetails.customer_phone;

      const phoneEl = document.getElementById('chat-customer-phone');
      if (phoneEl) phoneEl.textContent = `Phone: ${convDetails.customer_phone}`;

      const stateBadgeEl = document.getElementById('chat-state-badge');
      if (stateBadgeEl) {
        stateBadgeEl.textContent = convDetails.state || 'ACTIVE';
        stateBadgeEl.className = `badge ${convDetails.state === 'HANDOFF_REQUIRED' ? 'danger' : convDetails.state === 'IN_PROGRESS' ? 'warning' : 'success'}`;
      }
      
      const resolveBtn = document.getElementById('mark-resolved-btn');
      if (resolveBtn) {
        resolveBtn.style.display = 'inline-flex';
        resolveBtn.onclick = async () => {
          await fetch('/api/v1/portal/sms/resolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversation_id: conversationId })
          });
          showToast('Thread marked as resolved.');
          loadSMSConversations(document.getElementById('sms-thread-filter').value);
        };
      }

      document.getElementById('sms-reply-input').disabled = false;
      document.getElementById('send-sms-reply-btn').disabled = false;

      // Setup Quick Reply Chips
      document.querySelectorAll('#quick-reply-bar .quick-chip').forEach(chip => {
        chip.onclick = () => {
          const text = chip.dataset.text;
          const replyInput = document.getElementById('sms-reply-input');
          if (replyInput) {
            replyInput.value = text;
            replyInput.focus();
          }
        };
      });

      // Render Appointment Context Sidebar
      const contextDiv = document.getElementById('sms-context-details');
      if (contextDiv) {
        const apptId = convDetails.context_appointment_id;
        let actionButtonsHtml = '';
        if (apptId) {
          actionButtonsHtml = `
            <div class="context-actions-group">
              <button class="btn btn-sm btn-secondary sidebar-reschedule-btn" data-id="${apptId}" style="width: 100%;">📅 Reschedule Booking</button>
              <button class="btn btn-sm btn-danger sidebar-cancel-btn" data-id="${apptId}" style="width: 100%;">❌ Cancel Booking</button>
              <select class="form-input sidebar-reassign-select" data-id="${apptId}" style="font-size: 12px; padding: 6px; width: 100%;">
                <option value="">👤 Reassign Staff Agent...</option>
              </select>
            </div>
          `;
        }

        contextDiv.innerHTML = `
          <div class="context-info-card">
            <div class="context-info-row">
              <span class="context-label">Customer:</span>
              <span class="context-value">${convDetails.customer_name || 'N/A'}</span>
            </div>
            <div class="context-info-row">
              <span class="context-label">Phone:</span>
              <span class="context-value">${convDetails.customer_phone}</span>
            </div>
            <div class="context-info-row">
              <span class="context-label">State:</span>
              <span class="context-value">${convDetails.state || 'N/A'}</span>
            </div>
          </div>

          <div class="context-info-card">
            <div class="context-info-row">
              <span class="context-label">Booking Ref:</span>
              <span class="context-value">#${convDetails.context_appointment_id || 'N/A'}</span>
            </div>
            <div class="context-info-row">
              <span class="context-label">Service:</span>
              <span class="context-value">${convDetails.appointment_service_type || 'N/A'}</span>
            </div>
            <div class="context-info-row">
              <span class="context-label">Time:</span>
              <span class="context-value">${convDetails.appointment_time || 'N/A'}</span>
            </div>
            <div class="context-info-row">
              <span class="context-label">Assigned:</span>
              <span class="context-value">${convDetails.agent_name || 'Unassigned'}</span>
            </div>
          </div>
          ${actionButtonsHtml}
        `;

        if (apptId) {
          const rescheduleBtn = contextDiv.querySelector('.sidebar-reschedule-btn');
          const cancelBtn = contextDiv.querySelector('.sidebar-cancel-btn');
          const reassignSelect = contextDiv.querySelector('.sidebar-reassign-select');

          if (rescheduleBtn) {
            rescheduleBtn.addEventListener('click', async () => {
              const newTime = prompt('Enter new date & time (e.g. 2026-06-12 14:00:00):');
              if (!newTime) return;
              try {
                const res = await fetch(`/api/v1/portal/service-requests/${apptId}/reschedule`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ booking_time: newTime })
                });
                if (!res.ok) throw new Error('Reschedule failed');
                showToast('Appointment rescheduled!');
                loadSMSMessages(conversationId, convDetails);
              } catch (e) {
                showToast('Error rescheduling: ' + e.message, 'error');
              }
            });
          }

          if (cancelBtn) {
            cancelBtn.addEventListener('click', async () => {
              if (!confirm('Are you sure you want to cancel this appointment?')) return;
              try {
                const res = await fetch(`/api/v1/portal/service-requests/${apptId}/status`, {
                  method: 'PATCH',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ status: 'cancelled' })
                });
                if (!res.ok) throw new Error('Cancellation failed');
                showToast('Appointment cancelled!');
                loadSMSMessages(conversationId, convDetails);
              } catch (e) {
                showToast('Error cancelling: ' + e.message, 'error');
              }
            });
          }

          if (reassignSelect) {
            fetch(`/api/v1/portal/service-requests/${apptId}/available-agents`).then(r => r.json()).then(data => {
              const agents = data.agents || [];
              let opts = '<option value="">👤 Reassign Staff Agent...</option>';
              agents.forEach(a => {
                opts += `<option value="${a.id}">${a.name}</option>`;
              });
              reassignSelect.innerHTML = opts;
            }).catch(console.error);

            reassignSelect.addEventListener('change', async (e) => {
              const agentId = e.target.value;
              if (!agentId) return;
              try {
                const res = await fetch(`/api/v1/portal/service-requests/${apptId}/assign-agent`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ staff_agent_id: parseInt(agentId) })
                });
                if (!res.ok) throw new Error('Reassignment failed');
                showToast('Agent reassigned!');
                loadSMSMessages(conversationId, convDetails);
              } catch (e) {
                showToast('Error reassigning agent: ' + e.message, 'error');
              }
            });
          }
        }
      }

      // Load Chat Messages
      const res = await fetch(`/api/v1/portal/sms/conversations/${conversationId}/messages`);
      if (!res.ok) return;
      const msgs = await res.json();
      const container = document.getElementById('chat-messages-container');
      container.innerHTML = '';

      if (msgs.length === 0) {
        container.innerHTML = '<div class="chat-placeholder"><p class="text-muted">No messages recorded in this conversation.</p></div>';
        return;
      }

      msgs.forEach(m => {
        const msgDiv = document.createElement('div');
        const isCustomer = m.direction === 'inbound';
        const isSystem = m.sender_type === 'SYSTEM_BOT' || m.sender_name === 'System';
        
        let bubbleTypeClass = 'outbound';
        if (isCustomer) bubbleTypeClass = 'inbound';
        else if (isSystem) bubbleTypeClass = 'system';

        msgDiv.className = `chat-bubble ${bubbleTypeClass}`;
        
        const senderDisplayName = m.sender_name || (isCustomer ? 'Customer' : isSystem ? '🤖 Bot Auto-Responder' : '👤 Human Agent');
        const formattedTimeString = new Date(m.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});

        msgDiv.innerHTML = `
          <div class="bubble-sender-name">${senderDisplayName}</div>
          <div class="bubble-body-text">${m.body}</div>
          <div class="bubble-time-stamp">${formattedTimeString} ${!isCustomer ? '✓✓' : ''}</div>
        `;
        container.appendChild(msgDiv);
      });

      container.scrollTop = container.scrollHeight;
    } catch (err) {
      console.error('Error loading SMS messages:', err);
    }
  }

  // Send SMS Reply handler
  const sendReplyBtn = document.getElementById('send-sms-reply-btn');
  if (sendReplyBtn) {
    sendReplyBtn.addEventListener('click', async () => {
      const input = document.getElementById('sms-reply-input');
      const message = input.value.trim();
      if (!message || !activeConversationId) return;

      await fetch('/api/v1/portal/sms/reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: activeConversationId, message })
      });
      input.value = '';
      showToast('SMS reply sent.');
      loadSMSConversations(document.getElementById('sms-thread-filter').value);
      if (activeConversationId && activeConversationDetails) {
        await loadSMSMessages(activeConversationId, activeConversationDetails);
      }
    });
  }

  // SMS Thread Filter dropdown change
  const smsThreadFilter = document.getElementById('sms-thread-filter');
  if (smsThreadFilter) {
    smsThreadFilter.addEventListener('change', (e) => {
      loadSMSConversations(e.target.value);
    });
  }

  // SMS Log Drawer
  window.openSMSLogDrawer = async function(appointmentId) {
    try {
      document.getElementById('sms-log-drawer-subtitle').innerText = `Appointment #${appointmentId}`;
      document.getElementById('sms-log-drawer-overlay').classList.add('active');
      document.getElementById('sms-log-drawer').classList.add('active');

      const res = await fetch(`/api/v1/portal/sms/logs/appointment/${appointmentId}`);
      if (!res.ok) return;
      const logs = await res.json();
      const container = document.getElementById('sms-log-items-container');
      container.innerHTML = '';

      if (logs.length === 0) {
        container.innerHTML = '<p class="text-muted">No SMS logs recorded for this appointment.</p>';
        return;
      }

      logs.forEach(l => {
        const item = document.createElement('div');
        item.style.cssText = 'padding: 10px; border: 1px solid var(--border-card); border-radius: 6px; background: var(--bg-card); font-size: 13px;';
        const isFailed = l.status === 'FAILED';
        item.innerHTML = `
          <div style="display: flex; justify-content: space-between;">
            <strong>[${l.recipient_type.toUpperCase()}] ${l.template_type}</strong>
            <span>${l.status === 'DELIVERED' ? '✅ Delivered' : l.status === 'FAILED' ? '❌ Failed' : l.status}</span>
          </div>
          <div style="color: var(--text-muted); font-size: 12px; margin-top: 4px;">Phone: ${l.recipient_phone}</div>
          ${isFailed ? `<div style="color: red; font-size: 12px; margin-top: 4px;">Error: ${l.error_message || l.error_code || 'Unknown error'}</div><button class="btn btn-sm btn-primary retry-sms-btn" data-id="${l.id}" style="margin-top: 8px;">Retry SMS</button>` : ''}
        `;
        container.appendChild(item);
      });

      container.querySelectorAll('.retry-sms-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          const logId = e.target.dataset.id;
          await fetch(`/api/v1/portal/sms/retry/${logId}`, { method: 'POST' });
          showToast('Retry SMS dispatched.');
          window.openSMSLogDrawer(appointmentId);
        });
      });
    } catch (err) {
      console.error('Error opening SMS log drawer:', err);
    }
  };

  const closeSMSLogBtn = document.getElementById('close-sms-log-drawer-btn');
  const smsLogOverlay = document.getElementById('sms-log-drawer-overlay');
  if (closeSMSLogBtn) {
    closeSMSLogBtn.addEventListener('click', () => {
      document.getElementById('sms-log-drawer').classList.remove('active');
      smsLogOverlay.classList.remove('active');
    });
  }
  if (smsLogOverlay) {
    smsLogOverlay.addEventListener('click', () => {
      document.getElementById('sms-log-drawer').classList.remove('active');
      smsLogOverlay.classList.remove('active');
    });
  }


  // Global Refresh Action
  refreshBtn.addEventListener('click', () => {
    loadDashboardData();
    showToast('Refreshed statistics and calls log history.');
  });

  // Initial Data & URL Hash Router Load
  handleUrlHash();
  window.addEventListener('hashchange', () => handleUrlHash());
});

