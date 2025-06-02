document.addEventListener('DOMContentLoaded', function() {
    // Initialize variables
    let currentPage = 1;
    let perPage = 10;
    let searchQuery = '';
    let totalPages = 1;
    let isSidebarActive = false;

    // Initialize Socket.IO connection
    const socket = io();
    
    // Update current time
    function updateTime() {
        const now = new Date();
        document.getElementById('current-time').textContent = now.toLocaleTimeString();
    }
    setInterval(updateTime, 1000);
    updateTime();

    // Toggle sidebar
    const sidebar = document.getElementById('sidebar');
    const content = document.getElementById('content');
    const sidebarCollapse = document.getElementById('sidebarCollapse');

    function toggleSidebar() {
        isSidebarActive = !isSidebarActive;
        sidebar.classList.toggle('active');
        content.classList.toggle('active');
        
        // Store the state in localStorage
        localStorage.setItem('sidebarState', isSidebarActive ? 'active' : 'inactive');
    }

    // Initialize sidebar state from localStorage
    const savedState = localStorage.getItem('sidebarState');
    if (savedState === 'active') {
        isSidebarActive = true;
        sidebar.classList.add('active');
        content.classList.add('active');
    }

    sidebarCollapse.addEventListener('click', function(e) {
        e.preventDefault();
        toggleSidebar();
    });

    // Search functionality
    document.getElementById('searchButton').addEventListener('click', function() {
        searchQuery = document.getElementById('plateSearch').value.trim();
        currentPage = 1;
        updateActivityTable();
    });

    document.getElementById('plateSearch').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            searchQuery = this.value.trim();
            currentPage = 1;
            updateActivityTable();
        }
    });

    // Per page selection
    document.getElementById('perPageSelect').addEventListener('change', function() {
        perPage = parseInt(this.value);
        currentPage = 1;
        updateActivityTable();
    });

    // Format currency
    function formatCurrency(amount) {
        return `RWF ${amount.toLocaleString()}`;
    }

    // Format date
    function formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleString();
    }

    // Format duration
    function formatDuration(hours) {
        if (!hours) return '-';
        const wholeHours = Math.floor(hours);
        const minutes = Math.round((hours - wholeHours) * 60);
        return `${wholeHours}h ${minutes}m`;
    }

    // Get status badge HTML
    function getStatusBadge(status) {
        const badges = {
            'active': '<span class="status-badge status-active">Active</span>',
            'exit': '<span class="status-badge status-exit">Exited</span>',
            'alert': '<span class="status-badge status-alert">Alert</span>'
        };
        return badges[status] || badges['active'];
    }

    // Get alert badge HTML
    function getAlertBadge(resolved) {
        return resolved ? 
            '<span class="badge bg-success">Resolved</span>' : 
            '<span class="badge bg-danger">Active</span>';
    }

    // Update stats
    function updateStats() {
        fetch('/api/stats')
            .then(response => response.json())
            .then(data => {
                document.getElementById('total-vehicles').textContent = data.total_vehicles;
                document.getElementById('current-vehicles').textContent = data.current_vehicles;
                document.getElementById('total-revenue').textContent = formatCurrency(data.total_revenue);
            })
            .catch(error => console.error('Error fetching stats:', error));
    }

    // Update alerts
    function updateAlerts() {
        fetch('/api/alerts')
            .then(response => response.json())
            .then(alerts => {
                const tbody = document.getElementById('alerts-table');
                tbody.innerHTML = alerts.map(alert => `
                    <tr class="${alert.resolved ? '' : 'table-warning'}">
                        <td>${formatDate(alert.timestamp)}</td>
                        <td>${alert.plate}</td>
                        <td>${alert.alert_type}</td>
                        <td>${alert.gate_location}</td>
                        <td>${alert.description}</td>
                        <td>${getAlertBadge(alert.resolved)}</td>
                        <td>
                            ${!alert.resolved ? 
                                `<button class="btn btn-sm btn-success resolve-alert" data-id="${alert.id}">
                                    Resolve
                                </button>` : 
                                ''
                            }
                        </td>
                    </tr>
                `).join('');

                // Add event listeners to resolve buttons
                document.querySelectorAll('.resolve-alert').forEach(button => {
                    button.addEventListener('click', function() {
                        const alertId = this.dataset.id;
                        resolveAlert(alertId);
                    });
                });

                // Update active alerts count
                const activeAlerts = alerts.filter(alert => !alert.resolved).length;
                document.getElementById('active-alerts').textContent = activeAlerts;
            })
            .catch(error => console.error('Error fetching alerts:', error));
    }

    // Resolve alert
    function resolveAlert(alertId) {
        fetch('/api/resolve_alert', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                alert_id: alertId
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                updateAlerts();
                showNotification('Alert resolved successfully');
            } else {
                showNotification(`Error: ${data.message}`, 'error');
            }
        })
        .catch(error => {
            console.error('Error resolving alert:', error);
            showNotification('Error resolving alert', 'error');
        });
    }

    // Update activity table with pagination and search
    function updateActivityTable() {
        const token = localStorage.getItem('token');
        if (!token) {
            login('admin', 'admin123');
            return;
        }

        const url = new URL('/api/logs', window.location.origin);
        url.searchParams.set('page', currentPage);
        url.searchParams.set('per_page', perPage);
        if (searchQuery) {
            url.searchParams.set('plate', searchQuery);
        }

        fetch(url, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        })
        .then(response => {
            if (response.status === 401) {
                login('admin', 'admin123');
                return;
            }
            return response.json();
        })
        .then(data => {
            if (!data) return;
            
            const tbody = document.getElementById('activity-table');
            tbody.innerHTML = data.logs.map(log => `
                <tr>
                    <td>${log.id}</td>
                    <td>${log.plate}</td>
                    <td>${formatDate(log.entry_time)}</td>
                    <td>${log.exit_time ? formatDate(log.exit_time) : '-'}</td>
                    <td>${formatDuration(log.duration_hours)}</td>
                    <td>${getStatusBadge(log.status)}</td>
                    <td>
                        ${log.paid ? 
                            `<span class="text-success">✅ Paid (${formatCurrency(log.payment_amount)})</span>` : 
                            log.status === 'active' ?
                                `<button class="btn btn-sm btn-primary process-payment" data-plate="${log.plate}">Process Payment</button>` :
                                `<button class="btn btn-sm btn-success process-exit" data-plate="${log.plate}">Process Exit</button>`
                        }
                    </td>
                    <td>
                        <button class="btn btn-sm btn-info edit-record" data-id="${log.id}">
                            <i class='bx bx-edit'></i> Edit
                        </button>
                    </td>
                </tr>
            `).join('');

            // Update pagination info
            totalPages = data.pagination.pages;
            document.getElementById('currentPageStart').textContent = ((currentPage - 1) * perPage) + 1;
            document.getElementById('currentPageEnd').textContent = Math.min(currentPage * perPage, data.pagination.total);
            document.getElementById('totalRecords').textContent = data.pagination.total;

            // Update pagination controls
            updatePagination();

            // Add event listeners
            addTableEventListeners();
        })
        .catch(error => console.error('Error fetching logs:', error));
    }

    // Update pagination controls
    function updatePagination() {
        const pagination = document.getElementById('pagination');
        let html = '';

        // Previous button
        html += `
            <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${currentPage - 1}">Previous</a>
            </li>
        `;

        // Page numbers
        for (let i = 1; i <= totalPages; i++) {
            if (
                i === 1 || // First page
                i === totalPages || // Last page
                (i >= currentPage - 2 && i <= currentPage + 2) // Pages around current
            ) {
                html += `
                    <li class="page-item ${i === currentPage ? 'active' : ''}">
                        <a class="page-link" href="#" data-page="${i}">${i}</a>
                    </li>
                `;
            } else if (
                i === currentPage - 3 ||
                i === currentPage + 3
            ) {
                html += `
                    <li class="page-item disabled">
                        <span class="page-link">...</span>
                    </li>
                `;
            }
        }

        // Next button
        html += `
            <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${currentPage + 1}">Next</a>
            </li>
        `;

        pagination.innerHTML = html;

        // Add event listeners to pagination buttons
        pagination.querySelectorAll('.page-link').forEach(link => {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                const page = parseInt(this.dataset.page);
                if (page && page !== currentPage) {
                    currentPage = page;
                    updateActivityTable();
                }
            });
        });
    }

    // Add event listeners to table buttons
    function addTableEventListeners() {
        document.querySelectorAll('.process-payment').forEach(button => {
            button.addEventListener('click', function() {
                const plate = this.dataset.plate;
                processPayment(plate);
            });
        });

        document.querySelectorAll('.process-exit').forEach(button => {
            button.addEventListener('click', function() {
                const plate = this.dataset.plate;
                processExit(plate);
            });
        });

        document.querySelectorAll('.edit-record').forEach(button => {
            button.addEventListener('click', function() {
                const id = this.dataset.id;
                openEditModal(id);
            });
        });
    }

    // Login function
    function login(username, password) {
        fetch('/api/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                username: username,
                password: password
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.token) {
                localStorage.setItem('token', data.token);
                updateActivityTable();
            } else {
                showNotification('Login failed', 'error');
            }
        })
        .catch(error => {
            console.error('Error logging in:', error);
            showNotification('Login failed', 'error');
        });
    }

    // Update other API calls to include authentication
    function processPayment(plate) {
        const token = localStorage.getItem('token');
        fetch('/api/process_payment', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                plate: plate
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                updateActivityTable();
                updateStats();
                showNotification(`Payment processed for vehicle: ${plate} - ${formatCurrency(data.payment_amount)}`);
            } else {
                showNotification(`Error: ${data.message}`, 'error');
            }
        })
        .catch(error => {
            console.error('Error processing payment:', error);
            showNotification('Error processing payment', 'error');
        });
    }

    function processExit(plate) {
        const token = localStorage.getItem('token');
        fetch('/api/process_exit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                plate: plate
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                updateStats();
                updateActivityTable();
                showNotification(`Vehicle exited: ${plate} - Duration: ${formatDuration(data.duration_hours)} - Amount: ${formatCurrency(data.payment_amount)}`);
            } else {
                showNotification(`Error: ${data.message}`, 'error');
            }
        })
        .catch(error => {
            console.error('Error processing exit:', error);
            showNotification('Error processing exit', 'error');
        });
    }

    // Open edit modal
    function openEditModal(id) {
        fetch(`/api/logs/${id}`)
            .then(response => response.json())
            .then(log => {
                document.getElementById('editId').value = log.id;
                document.getElementById('editPlate').value = log.plate;
                document.getElementById('editEntryTime').value = formatDateTimeForInput(log.entry_time);
                document.getElementById('editExitTime').value = log.exit_time ? formatDateTimeForInput(log.exit_time) : '';
                document.getElementById('editPaymentAmount').value = log.payment_amount;
                document.getElementById('editStatus').value = log.status;

                const editModal = new bootstrap.Modal(document.getElementById('editModal'));
                editModal.show();
            })
            .catch(error => {
                console.error('Error fetching log details:', error);
                showNotification('Error loading record details', 'error');
            });
    }

    // Format datetime for input
    function formatDateTimeForInput(dateString) {
        if (!dateString) return '';
        const date = new Date(dateString);
        return date.toISOString().slice(0, 16);
    }

    // Save edit
    document.getElementById('saveEdit').addEventListener('click', function() {
        const id = document.getElementById('editId').value;
        const data = {
            plate: document.getElementById('editPlate').value,
            entry_time: document.getElementById('editEntryTime').value,
            exit_time: document.getElementById('editExitTime').value,
            payment_amount: document.getElementById('editPaymentAmount').value,
            status: document.getElementById('editStatus').value
        };

        fetch(`/api/logs/${id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                updateActivityTable();
                updateStats();
                showNotification('Record updated successfully');
                bootstrap.Modal.getInstance(document.getElementById('editModal')).hide();
            } else {
                showNotification(`Error: ${result.message}`, 'error');
            }
        })
        .catch(error => {
            console.error('Error updating record:', error);
            showNotification('Error updating record', 'error');
        });
    });

    // Socket.IO event handlers
    socket.on('new_vehicle', function(data) {
        updateStats();
        updateActivityTable();
        showNotification(`New vehicle entered: ${data.plate}`);
    });

    socket.on('vehicle_exit', function(data) {
        updateStats();
        updateActivityTable();
        showNotification(`Vehicle exited: ${data.plate} - Duration: ${formatDuration(data.duration_hours)} - Amount: ${formatCurrency(data.payment_amount)}`);
    });

    socket.on('payment_processed', function(data) {
        updateActivityTable();
        updateStats();
        showNotification(`Payment processed for ${data.plate}: ${formatCurrency(data.amount)}`);
    });

    socket.on('new_alert', function(data) {
        updateAlerts();
        showNotification(`New alert: ${data.description}`, 'warning');
    });

    socket.on('alert_resolved', function(data) {
        updateAlerts();
    });

    // Show notification
    function showNotification(message, type = 'info') {
        if ('Notification' in window) {
            if (Notification.permission === 'granted') {
                new Notification('Parking System', {
                    body: message,
                    icon: '/static/icon.png'
                });
            } else if (Notification.permission !== 'denied') {
                Notification.requestPermission().then(permission => {
                    if (permission === 'granted') {
                        new Notification('Parking System', {
                            body: message,
                            icon: '/static/icon.png'
                        });
                    }
                });
            }
        }

        // Show toast notification
        const toast = document.createElement('div');
        toast.className = `toast-notification ${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, 3000);
    }

    // Add refresh button event listener
    document.getElementById('refresh-alerts').addEventListener('click', updateAlerts);

    // Initial data load
    updateStats();
    updateActivityTable();
    updateAlerts();

    // Refresh data every 10 seconds
    setInterval(() => {
        updateStats();
        updateActivityTable();
        updateAlerts();
    }, 10000);
}); 