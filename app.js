// Инициализация Telegram Web App
const tg = window.Telegram.WebApp;
tg.expand();
tg.enableClosingConfirmation();

// API URL (замените на ваш реальный URL)
const API_URL = 'https://ваш-бот-на-railway.railway.app/api';

// Текущий пользователь
let currentUser = {
    id: tg.initDataUnsafe?.user?.id || 0,
    firstName: tg.initDataUnsafe?.user?.first_name || 'Пользователь'
};

// Состояние приложения
let allRequests = [];
let allAlerts = [];

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    // Устанавливаем информацию о пользователе
    document.getElementById('userName').textContent = currentUser.firstName;
    
    // Настройка цветовой схемы Telegram
    document.body.style.backgroundColor = tg.themeParams.bg_color || '#ffffff';
    
    // Инициализация табов
    initTabs();
    
    // Инициализация формы
    initForm();
    
    // Загрузка данных
    loadDashboardData();
    loadRequests();
    loadAlerts();
});

// Инициализация табов
function initTabs() {
    const tabs = document.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('.tab-content');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabId = tab.dataset.tab;
            
            // Обновляем активные табы
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            contents.forEach(c => c.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            
            // При переключении на вкладку запросов обновляем данные
            if (tabId === 'requests') {
                loadRequests();
            }
            
            // При переключении на вкладку оповещений обновляем данные
            if (tabId === 'alerts') {
                loadAlerts();
            }
        });
    });
}

// Инициализация формы
function initForm() {
    // Приоритетные кнопки
    const priorityBtns = document.querySelectorAll('.priority-btn');
    priorityBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            priorityBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('requestPriority').value = btn.dataset.priority;
        });
    });
    
    // Устанавливаем активный приоритет по умолчанию
    document.querySelector('.priority-btn[data-priority="medium"]').classList.add('active');
    
    // Отправка формы
    const form = document.getElementById('newRequestForm');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await createChangeRequest();
    });
    
    // Кнопка создания оповещения
    const createAlertBtn = document.getElementById('createAlertBtn');
    if (createAlertBtn) {
        createAlertBtn.addEventListener('click', () => {
            openAlertModal();
        });
    }
    
    // Модальное окно
    const modal = document.getElementById('alertModal');
    const modalClose = modal.querySelector('.modal-close');
    const cancelBtn = modal.querySelector('.cancel-btn');
    const sendBtn = modal.querySelector('.send-alert-btn');
    
    modalClose.addEventListener('click', () => closeAlertModal());
    cancelBtn.addEventListener('click', () => closeAlertModal());
    sendBtn.addEventListener('click', () => sendUrgentAlert());
    
    // Фильтры
    const priorityFilter = document.getElementById('priorityFilter');
    const statusFilter = document.getElementById('statusFilter');
    const refreshBtn = document.getElementById('refreshRequests');
    
    if (priorityFilter) {
        priorityFilter.addEventListener('change', () => filterRequests());
    }
    if (statusFilter) {
        statusFilter.addEventListener('change', () => filterRequests());
    }
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => loadRequests());
    }
}

// Загрузка данных для дашборда
async function loadDashboardData() {
    try {
        const response = await fetch(`${API_URL}/stats?user_id=${currentUser.id}`);
        const data = await response.json();
        
        document.getElementById('totalRequests').textContent = data.totalRequests || 0;
        document.getElementById('pendingRequests').textContent = data.pendingRequests || 0;
        document.getElementById('highPriority').textContent = data.highPriority || 0;
        document.getElementById('activeAlerts').textContent = data.activeAlerts || 0;
        
    } catch (error) {
        console.error('Error loading dashboard data:', error);
        // Используем демо-данные
        document.getElementById('totalRequests').textContent = '12';
        document.getElementById('pendingRequests').textContent = '5';
        document.getElementById('highPriority').textContent = '3';
        document.getElementById('activeAlerts').textContent = '2';
    }
}

// Загрузка запросов
async function loadRequests() {
    const requestsList = document.getElementById('requestsList');
    requestsList.innerHTML = '<div class="loading">Загрузка...</div>';
    
    try {
        const response = await fetch(`${API_URL}/requests?user_id=${currentUser.id}`);
        allRequests = await response.json();
        filterRequests();
        
    } catch (error) {
        console.error('Error loading requests:', error);
        // Демо-данные
        allRequests = [
            { id: 1, description: 'Обновить дашборд с метриками', priority: 'high', status: 'new', created_at: '2026-03-20', requester_name: 'Иван' },
            { id: 2, description: 'Добавить фильтры в отчет', priority: 'medium', status: 'new', created_at: '2026-03-19', requester_name: 'Петр' },
            { id: 3, description: 'Исправить ошибку в расчетах', priority: 'high', status: 'in_review', created_at: '2026-03-18', requester_name: 'Мария' }
        ];
        filterRequests();
    }
}

// Фильтрация запросов
function filterRequests() {
    const priorityFilter = document.getElementById('priorityFilter').value;
    const statusFilter = document.getElementById('statusFilter').value;
    
    let filtered = [...allRequests];
    
    if (priorityFilter !== 'all') {
        filtered = filtered.filter(r => r.priority === priorityFilter);
    }
    
    if (statusFilter !== 'all') {
        filtered = filtered.filter(r => r.status === statusFilter);
    }
    
    renderRequests(filtered);
}

// Отображение запросов
function renderRequests(requests) {
    const container = document.getElementById('requestsList');
    
    if (requests.length === 0) {
        container.innerHTML = '<div class="loading">Нет запросов</div>';
        return;
    }
    
    container.innerHTML = requests.map(req => `
        <div class="request-card priority-${req.priority}">
            <div class="request-header">
                <span class="request-id">#${req.id}</span>
                <span class="request-priority">${getPriorityText(req.priority)}</span>
            </div>
            <div class="request-description">${escapeHtml(req.description)}</div>
            <div class="request-meta">
                <span>👤 ${req.requester_name || 'Неизвестно'}</span>
                <span>📅 ${req.created_at || 'Нет даты'}</span>
                <span>📌 ${getStatusText(req.status)}</span>
            </div>
        </div>
    `).join('');
}

// Загрузка оповещений
async function loadAlerts() {
    const alertsList = document.getElementById('alertsList');
    alertsList.innerHTML = '<div class="loading">Загрузка...</div>';
    
    try {
        const response = await fetch(`${API_URL}/alerts?user_id=${currentUser.id}`);
        allAlerts = await response.json();
        renderAlerts(allAlerts);
        
    } catch (error) {
        console.error('Error loading alerts:', error);
        // Демо-данные
        allAlerts = [
            { id: 1, description: 'Не работает дашборд с метриками', is_resolved: 0, created_at: '2026-03-20 10:30' },
            { id: 2, description: 'Сорван дедлайн по отчету', is_resolved: 0, created_at: '2026-03-20 09:15' }
        ];
        renderAlerts(allAlerts);
    }
}

// Отображение оповещений
function renderAlerts(alerts) {
    const container = document.getElementById('alertsList');
    
    if (alerts.length === 0) {
        container.innerHTML = '<div class="loading">Нет активных оповещений</div>';
        return;
    }
    
    container.innerHTML = alerts.map(alert => `
        <div class="alert-card">
            <div class="alert-header">
                <span class="alert-id">⚠️ #${alert.id}</span>
                <span class="alert-date">${alert.created_at || 'Нет даты'}</span>
            </div>
            <div class="alert-description">${escapeHtml(alert.description)}</div>
            <div class="alert-status">
                ${alert.is_resolved ? '✅ Решено' : '🟡 Активно'}
            </div>
        </div>
    `).join('');
}

// Создание запроса на изменение
async function createChangeRequest() {
    const description = document.getElementById('requestDescription').value;
    const priority = document.getElementById('requestPriority').value;
    const documentLink = document.getElementById('requestDocumentLink').value;
    const businessImpact = document.getElementById('requestBusinessImpact').value;
    
    if (!description.trim()) {
        tg.showAlert('Пожалуйста, опишите запрос');
        return;
    }
    
    const data = {
        user_id: currentUser.id,
        description: description,
        priority: priority,
        document_link: documentLink,
        business_impact: businessImpact
    };
    
    try {
        const response = await fetch(`${API_URL}/change_request`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            tg.showAlert('✅ Запрос успешно создан!');
            // Очищаем форму
            document.getElementById('requestDescription').value = '';
            document.getElementById('requestDocumentLink').value = '';
            document.getElementById('requestBusinessImpact').value = '';
            // Переключаемся на вкладку запросов
            document.querySelector('[data-tab="requests"]').click();
            loadRequests();
            loadDashboardData();
        } else {
            tg.showAlert('❌ Ошибка при создании запроса');
        }
        
    } catch (error) {
        console.error('Error creating request:', error);
        tg.showAlert('✅ Запрос создан! (демо-режим)');
        document.querySelector('[data-tab="requests"]').click();
        loadRequests();
        loadDashboardData();
    }
}

// Открытие модального окна оповещения
function openAlertModal() {
    const modal = document.getElementById('alertModal');
    modal.classList.add('active');
    document.getElementById('alertDescription').value = '';
}

// Закрытие модального окна
function closeAlertModal() {
    const modal = document.getElementById('alertModal');
    modal.classList.remove('active');
}

// Отправка срочного оповещения
async function sendUrgentAlert() {
    const description = document.getElementById('alertDescription').value;
    
    if (!description.trim()) {
        tg.showAlert('Пожалуйста, опишите проблему');
        return;
    }
    
    const data = {
        user_id: currentUser.id,
        description: description
    };
    
    try {
        const response = await fetch(`${API_URL}/urgent_alert`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            tg.showAlert('⚠️ Срочное оповещение отправлено!');
            closeAlertModal();
            loadAlerts();
            loadDashboardData();
        } else {
            tg.showAlert('❌ Ошибка при отправке оповещения');
        }
        
    } catch (error) {
        console.error('Error sending alert:', error);
        tg.showAlert('⚠️ Оповещение отправлено! (демо-режим)');
        closeAlertModal();
        loadAlerts();
        loadDashboardData();
    }
}

// Вспомогательные функции
function getPriorityText(priority) {
    const map = { high: '🔴 Высокий', medium: '🟡 Средний', low: '🟢 Низкий' };
    return map[priority] || priority;
}

function getStatusText(status) {
    const map = { 
        new: '🆕 Новый', 
        in_review: '👀 На рассмотрении', 
        approved: '✅ Одобрен', 
        rejected: '❌ Отклонен' 
    };
    return map[status] || status;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Экспорт для использования в Telegram
window.tg = tg;