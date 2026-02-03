// ===================================
// SKYLINE AIRWAYS - MAIN APPLICATION
// ===================================

// Configuration
const API_BASE_URL = 'http://127.0.0.1:8000';

// State Management
const state = {
  user: null,
  authToken: null,
  sessionId: null,
  searchResults: [],
  selectedFlight: null,
  currentPage: 'home'
};

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
  initAuth();
  initNavigation();
  initSearchForm();
  setupScrollEffect();
  setMinDate();
});

// ===================================
// AUTHENTICATION
// ===================================

function initAuth() {
  // Check for stored auth
  const storedToken = localStorage.getItem('auth_token');
  const storedUser = localStorage.getItem('user_data');

  if (storedToken && storedUser) {
    state.authToken = storedToken;
    state.user = JSON.parse(storedUser);
    updateAuthUI();
  }
}

function updateAuthUI() {
  const authLink = document.getElementById('authLink');
  if (state.user) {
    authLink.textContent = `👤 ${state.user.name}`;
    authLink.onclick = (e) => {
      e.preventDefault();
      showUserMenu();
    };
  } else {
    authLink.textContent = 'Login';
    authLink.onclick = (e) => {
      e.preventDefault();
      navigateTo('auth');
    };
  }
}

function showUserMenu() {
  const menu = document.createElement('div');
  menu.className = 'modal-overlay';
  menu.innerHTML = `
    <div class="modal" style="max-width: 300px;">
      <div class="modal-header">
        <h3 class="modal-title">Account</h3>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">×</button>
      </div>
      <div class="modal-body">
        <p><strong>${state.user.name}</strong></p>
        <p style="color: var(--gray-500); font-size: 0.875rem;">${state.user.email}</p>
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="navigateTo('dashboard'); this.closest('.modal-overlay').remove();">My Bookings</button>
        <button class="btn btn-secondary" onclick="logout(); this.closest('.modal-overlay').remove();">Logout</button>
      </div>
    </div>
  `;
  document.body.appendChild(menu);
}

function logout() {
  localStorage.removeItem('auth_token');
  localStorage.removeItem('user_data');
  localStorage.removeItem('chat_session_id');
  state.user = null;
  state.authToken = null;
  state.sessionId = null;
  updateAuthUI();
  navigateTo('home');
  showNotification('Logged out successfully', 'info');
}

// ===================================
// NAVIGATION & ROUTING
// ===================================

function initNavigation() {
  // Handle navigation links
  document.querySelectorAll('[data-page]').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const page = e.target.dataset.page;
      navigateTo(page);
    });
  });
}

async function navigateTo(page) {
  state.currentPage = page;

  // Update active nav link
  document.querySelectorAll('.navbar-link').forEach(link => {
    link.classList.remove('active');
    if (link.dataset.page === page || (page === 'home' && link.getAttribute('href') === '#home')) {
      link.classList.add('active');
    }
  });

  const app = document.getElementById('app');

  switch (page) {
    case 'home':
      window.location.reload();
      break;
    case 'search':
      await loadSearchPage();
      break;
    case 'booking':
      await loadBookingPage();
      break;
    case 'dashboard':
      if (!state.user) {
        showNotification('Please login to view your bookings', 'warning');
        navigateTo('auth');
        return;
      }
      await loadDashboardPage();
      break;
    case 'auth':
      await loadAuthPage();
      break;
  }
}

// ===================================
// SEARCH FUNCTIONALITY
// ===================================

function initSearchForm() {
  const form = document.getElementById('searchForm');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    await performSearch();
  });
}

function setMinDate() {
  const dateInput = document.getElementById('searchDate');
  const today = new Date().toISOString().split('T')[0];
  dateInput.min = today;
  dateInput.value = today;
}

async function performSearch() {
  const origin = document.getElementById('searchOrigin').value.trim();
  const destination = document.getElementById('searchDestination').value.trim();
  const date = document.getElementById('searchDate').value;

  if (!origin || !destination || !date) {
    showNotification('Please fill in all search fields', 'warning');
    return;
  }

  // Store search params
  state.searchParams = { origin, destination, date };

  // Show loading
  showNotification('Searching for flights...', 'info');

  try {
    // Use the chat API to search for flights
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: `search flights from ${origin} to ${destination} on ${date}`,
        session_id: state.sessionId,
        token: state.authToken
      })
    });

    const data = await response.json();

    if (data.session_id && !state.sessionId) {
      state.sessionId = data.session_id;
      localStorage.setItem('chat_session_id', state.sessionId);
    }

    // Parse flight results from response
    parseFlightResults(data.response);

    // Navigate to search results
    navigateTo('search');

  } catch (error) {
    showNotification('Failed to search flights. Please try again.', 'error');
    console.error('Search error:', error);
  }
}

function parseFlightResults(response) {
  // Extract flight information from the chat response
  const flights = [];
  const lines = response.split('\n');

  lines.forEach(line => {
    // Match pattern: • Airline FlightNum — Origin → Dest — Dep: DateTime — Fare: ₹Price
    const match = line.match(/•\s+(.+?)\s+(\w+)\s+—\s+(.+?)\s+→\s+(.+?)\s+—\s+Dep:\s+(.+?)\s+—\s+Fare:\s+₹([\d,]+)/);
    if (match) {
      flights.push({
        airline: match[1].trim(),
        flightNumber: match[2].trim(),
        origin: match[3].trim(),
        destination: match[4].trim(),
        departureTime: match[5].trim(),
        price: parseInt(match[6].replace(/,/g, ''))
      });
    }
  });

  state.searchResults = flights;
}

// ===================================
// PAGE LOADERS
// ===================================

async function loadSearchPage() {
  const app = document.getElementById('app');

  const flights = state.searchResults.length > 0 ? state.searchResults : getSampleFlights();

  app.innerHTML = `
    <div style="padding-top: 80px; min-height: 100vh; background: var(--gray-50);">
      <div class="container section">
        <div style="margin-bottom: var(--spacing-2xl);">
          <h1>Available Flights</h1>
          <p style="color: var(--gray-600);">
            ${state.searchParams ? `${state.searchParams.origin} → ${state.searchParams.destination} • ${formatDate(state.searchParams.date)}` : 'Search results'}
          </p>
        </div>
        
        <div class="grid" style="gap: var(--spacing-lg);">
          ${flights.map((flight, index) => `
            <div class="flight-card">
              <div class="flight-info">
                <div class="flight-time">${extractTime(flight.departureTime)}</div>
                <div class="flight-city">${flight.origin}</div>
                <div class="badge badge-info">${flight.airline}</div>
              </div>
              
              <div class="flight-route">
                <div class="flight-duration">2h 30m</div>
                <div class="flight-line"></div>
                <div>Direct</div>
              </div>
              
              <div class="flight-info">
                <div class="flight-time">${calculateArrival(flight.departureTime)}</div>
                <div class="flight-city">${flight.destination}</div>
                <div style="font-size: 0.875rem; color: var(--gray-500);">${flight.flightNumber}</div>
              </div>
              
              <div class="flight-price">
                <div class="price-amount">₹${flight.price.toLocaleString()}</div>
                <div class="price-label">per person</div>
                <button class="btn btn-primary mt-md" onclick="selectFlight(${index})">
                  Book Now
                </button>
              </div>
            </div>
          `).join('')}
        </div>
        
        ${flights.length === 0 ? `
          <div class="card text-center" style="padding: var(--spacing-3xl);">
            <div style="font-size: 4rem; margin-bottom: var(--spacing-lg);">✈️</div>
            <h3>No flights found</h3>
            <p>Try adjusting your search criteria</p>
            <button class="btn btn-primary mt-lg" onclick="navigateTo('home')">New Search</button>
          </div>
        ` : ''}
      </div>
    </div>
  `;
}

async function loadBookingPage() {
  if (!state.selectedFlight) {
    navigateTo('search');
    return;
  }

  if (!state.user) {
    showNotification('Please login to book a flight', 'warning');
    navigateTo('auth');
    return;
  }

  const flight = state.selectedFlight;
  const app = document.getElementById('app');

  app.innerHTML = `
    <div style="padding-top: 80px; min-height: 100vh; background: var(--gray-50);">
      <div class="container section">
        <h1 class="mb-xl">Complete Your Booking</h1>
        
        <div class="grid grid-2">
          <!-- Booking Form -->
          <div>
            <div class="card mb-lg">
              <h3>Passenger Details</h3>
              <form id="bookingForm">
                <div class="form-group">
                  <label class="form-label" style="color: var(--gray-700);">Full Name</label>
                  <input type="text" class="form-input" value="${state.user.name}" required>
                </div>
                <div class="form-group">
                  <label class="form-label" style="color: var(--gray-700);">Email</label>
                  <input type="email" class="form-input" value="${state.user.email}" required>
                </div>
                <div class="form-group">
                  <label class="form-label" style="color: var(--gray-700);">Phone</label>
                  <input type="tel" class="form-input" placeholder="+91 98765 43210" required>
                </div>
              </form>
            </div>
            
            <div class="card mb-lg">
              <h3>Seat Selection</h3>
              <div class="form-group">
                <label class="form-label" style="color: var(--gray-700);">Preferred Seat</label>
                <input type="text" class="form-input" id="seatNumber" placeholder="e.g., 12A" required>
                <p style="font-size: 0.875rem; color: var(--gray-500); margin-top: var(--spacing-sm);">
                  Enter your preferred seat (e.g., 12A, 15C)
                </p>
              </div>
            </div>
            
            <div class="card">
              <h3>Payment Method</h3>
              <div class="form-group">
                <select class="form-select" id="paymentMethod" required>
                  <option value="">Select payment method</option>
                  <option value="UPI">UPI</option>
                  <option value="Credit Card">Credit Card</option>
                  <option value="Debit Card">Debit Card</option>
                  <option value="Net Banking">Net Banking</option>
                </select>
              </div>
            </div>
          </div>
          
          <!-- Booking Summary -->
          <div>
            <div class="card" style="position: sticky; top: 100px;">
              <h3>Booking Summary</h3>
              <div style="padding: var(--spacing-lg); background: var(--gray-50); border-radius: var(--radius-md); margin: var(--spacing-lg) 0;">
                <div class="flex justify-between mb-md">
                  <span style="color: var(--gray-600);">Flight</span>
                  <span style="font-weight: 600;">${flight.airline} ${flight.flightNumber}</span>
                </div>
                <div class="flex justify-between mb-md">
                  <span style="color: var(--gray-600);">Route</span>
                  <span style="font-weight: 600;">${flight.origin} → ${flight.destination}</span>
                </div>
                <div class="flex justify-between mb-md">
                  <span style="color: var(--gray-600);">Departure</span>
                  <span style="font-weight: 600;">${flight.departureTime}</span>
                </div>
                <div class="flex justify-between mb-md">
                  <span style="color: var(--gray-600);">Passengers</span>
                  <span style="font-weight: 600;">1 Adult</span>
                </div>
                <hr style="border: none; border-top: 1px solid var(--gray-300); margin: var(--spacing-lg) 0;">
                <div class="flex justify-between" style="font-size: 1.25rem; font-weight: 700;">
                  <span>Total</span>
                  <span style="color: var(--primary-blue);">₹${flight.price.toLocaleString()}</span>
                </div>
              </div>
              
              <button class="btn btn-primary btn-lg" style="width: 100%;" onclick="confirmBooking()">
                Confirm Booking
              </button>
              
              <p style="font-size: 0.75rem; color: var(--gray-500); text-align: center; margin-top: var(--spacing-md);">
                By booking, you agree to our terms and conditions
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

async function loadDashboardPage() {
  const app = document.getElementById('app');

  app.innerHTML = `
    <div style="padding-top: 80px; min-height: 100vh; background: var(--gray-50);">
      <div class="container section">
        <h1 class="mb-xl">My Bookings</h1>
        <div id="bookingsContainer">
          <div class="text-center" style="padding: var(--spacing-3xl);">
            <div style="font-size: 2rem; margin-bottom: var(--spacing-md);">⏳</div>
            <p>Loading your bookings...</p>
          </div>
        </div>
      </div>
    </div>
  `;

  // Fetch bookings via chat API
  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: 'show my bookings',
        session_id: state.sessionId,
        token: state.authToken
      })
    });

    const data = await response.json();
    displayBookings(data.response);
  } catch (error) {
    document.getElementById('bookingsContainer').innerHTML = `
      <div class="card text-center">
        <p style="color: var(--error);">Failed to load bookings</p>
      </div>
    `;
  }
}

function displayBookings(response) {
  const container = document.getElementById('bookingsContainer');

  // Parse bookings from response
  if (response.includes('no bookings')) {
    container.innerHTML = `
      <div class="card text-center" style="padding: var(--spacing-3xl);">
        <div style="font-size: 4rem; margin-bottom: var(--spacing-lg);">📋</div>
        <h3>No bookings yet</h3>
        <p>Start your journey by booking your first flight</p>
        <button class="btn btn-primary mt-lg" onclick="navigateTo('home')">Search Flights</button>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="card">
      <pre style="white-space: pre-wrap; font-family: var(--font-sans); line-height: 1.8;">${response}</pre>
    </div>
  `;
}

async function loadAuthPage() {
  const app = document.getElementById('app');

  app.innerHTML = `
    <div style="padding-top: 80px; min-height: 100vh; background: var(--gradient-hero); display: flex; align-items: center; justify-content: center;">
      <div class="card" style="max-width: 450px; width: 100%; margin: var(--spacing-lg);">
        <h2 class="text-center mb-xl">Welcome Back</h2>
        
        <form id="loginForm">
          <div class="form-group">
            <label class="form-label" style="color: var(--gray-700);">Email</label>
            <input type="email" class="form-input" id="loginEmail" placeholder="your.email@example.com" required>
          </div>
          <div class="form-group">
            <label class="form-label" style="color: var(--gray-700);">Password</label>
            <input type="password" class="form-input" id="loginPassword" placeholder="Enter your password" required>
          </div>
          <div id="loginError" style="color: var(--error); font-size: 0.875rem; margin-bottom: var(--spacing-md);"></div>
          <button type="submit" class="btn btn-primary btn-lg" style="width: 100%;">Login</button>
        </form>
        
        <div style="margin-top: var(--spacing-xl); padding: var(--spacing-lg); background: var(--gray-50); border-radius: var(--radius-md);">
          <p style="font-weight: 600; margin-bottom: var(--spacing-sm);">Demo Credentials:</p>
          <p style="font-size: 0.875rem; margin: 0;">Email: aadhvik@email.com</p>
          <p style="font-size: 0.875rem; margin: 0;">Password: password123</p>
        </div>
      </div>
    </div>
  `;

  document.getElementById('loginForm').addEventListener('submit', handleLogin);
}

async function handleLogin(e) {
  e.preventDefault();

  const email = document.getElementById('loginEmail').value;
  const password = document.getElementById('loginPassword').value;
  const errorDiv = document.getElementById('loginError');

  errorDiv.textContent = '';

  try {
    const response = await fetch(`${API_BASE_URL}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    if (!response.ok) {
      const error = await response.json();
      errorDiv.textContent = error.detail || 'Login failed';
      return;
    }

    const data = await response.json();
    state.authToken = data.token;
    state.user = {
      customer_id: data.customer_id,
      name: data.name,
      email: data.email
    };

    localStorage.setItem('auth_token', state.authToken);
    localStorage.setItem('user_data', JSON.stringify(state.user));

    updateAuthUI();
    showNotification(`Welcome back, ${state.user.name}!`, 'success');
    navigateTo('home');

  } catch (error) {
    errorDiv.textContent = 'Could not connect to server';
  }
}

// ===================================
// BOOKING FUNCTIONS
// ===================================

function selectFlight(index) {
  state.selectedFlight = state.searchResults[index];
  navigateTo('booking');
}

async function confirmBooking() {
  const seat = document.getElementById('seatNumber').value.trim();
  const paymentMethod = document.getElementById('paymentMethod').value;

  if (!seat || !paymentMethod) {
    showNotification('Please fill in all required fields', 'warning');
    return;
  }

  const flight = state.selectedFlight;

  showNotification('Processing your booking...', 'info');

  try {
    // Use chat API to book
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: `book flight from ${flight.origin} to ${flight.destination} on ${state.searchParams.date}, seat ${seat}, payment ${paymentMethod}`,
        session_id: state.sessionId,
        token: state.authToken
      })
    });

    const data = await response.json();

    if (data.response.includes('Confirmed')) {
      showBookingConfirmation(data.response);
    } else {
      showNotification(data.response, 'info');
    }

  } catch (error) {
    showNotification('Booking failed. Please try again.', 'error');
  }
}

function showBookingConfirmation(message) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <h3 class="modal-title">✅ Booking Confirmed!</h3>
      </div>
      <div class="modal-body">
        <pre style="white-space: pre-wrap; font-family: var(--font-sans); line-height: 1.8;">${message}</pre>
      </div>
      <div class="modal-footer">
        <button class="btn btn-primary" onclick="this.closest('.modal-overlay').remove(); navigateTo('dashboard');">
          View My Bookings
        </button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
}

// ===================================
// UTILITIES
// ===================================

function showNotification(message, type = 'info') {
  const notification = document.createElement('div');
  notification.style.cssText = `
    position: fixed;
    top: 100px;
    right: 20px;
    z-index: 3000;
    padding: 1rem 1.5rem;
    background: white;
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-xl);
    border-left: 4px solid ${type === 'success' ? 'var(--success)' : type === 'error' ? 'var(--error)' : type === 'warning' ? 'var(--warning)' : 'var(--info)'};
    animation: slideInRight 0.3s ease-out;
    max-width: 400px;
  `;
  notification.textContent = message;
  document.body.appendChild(notification);

  setTimeout(() => {
    notification.style.animation = 'slideInRight 0.3s ease-out reverse';
    setTimeout(() => notification.remove(), 300);
  }, 3000);
}

function setupScrollEffect() {
  const navbar = document.getElementById('navbar');
  window.addEventListener('scroll', () => {
    if (window.scrollY > 50) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  });
}

function formatDate(dateStr) {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
}

function extractTime(datetime) {
  // Extract time from datetime string
  const match = datetime.match(/(\d{2}:\d{2})/);
  return match ? match[1] : '10:00';
}

function calculateArrival(departureTime) {
  // Simple calculation - add 2.5 hours
  const match = departureTime.match(/(\d{2}):(\d{2})/);
  if (match) {
    let hours = parseInt(match[1]);
    let minutes = parseInt(match[2]);
    minutes += 30;
    hours += 2;
    if (minutes >= 60) {
      hours += 1;
      minutes -= 60;
    }
    if (hours >= 24) hours -= 24;
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
  }
  return '12:30';
}

function getSampleFlights() {
  // Sample flights for demo
  return [
    {
      airline: 'Air India',
      flightNumber: 'AI101',
      origin: 'Delhi (DEL)',
      destination: 'Mumbai (BOM)',
      departureTime: '2025-12-15 10:00',
      price: 5500
    },
    {
      airline: 'IndiGo',
      flightNumber: '6E202',
      origin: 'Delhi (DEL)',
      destination: 'Mumbai (BOM)',
      departureTime: '2025-12-15 14:30',
      price: 4800
    },
    {
      airline: 'Vistara',
      flightNumber: 'UK303',
      origin: 'Delhi (DEL)',
      destination: 'Mumbai (BOM)',
      departureTime: '2025-12-15 18:00',
      price: 6200
    }
  ];
}

// ===================================
// CHAT WIDGET
// ===================================

let chatWidgetOpen = false;
let chatWidgetSessionId = null;

function initChatWidget() {
  const button = document.getElementById('chatWidgetButton');
  const container = document.getElementById('chatWidgetContainer');
  const closeBtn = document.getElementById('chatWidgetClose');
  const input = document.getElementById('chatWidgetInput');
  const sendBtn = document.getElementById('chatWidgetSend');

  // Toggle chat widget
  button.addEventListener('click', () => {
    toggleChatWidget();
  });

  closeBtn.addEventListener('click', () => {
    toggleChatWidget();
  });

  // Send message
  sendBtn.addEventListener('click', () => {
    sendChatMessage();
  });

  input.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      sendChatMessage();
    }
  });

  // Load chat session if exists
  const savedChatSession = localStorage.getItem('chat_widget_session_id');
  if (savedChatSession) {
    chatWidgetSessionId = savedChatSession;
  }
}

function toggleChatWidget() {
  const button = document.getElementById('chatWidgetButton');
  const container = document.getElementById('chatWidgetContainer');

  chatWidgetOpen = !chatWidgetOpen;

  if (chatWidgetOpen) {
    container.classList.remove('hidden');
    button.classList.add('active');
    button.innerHTML = '✕';

    // Show welcome message if first time
    const messagesContainer = document.getElementById('chatWidgetMessages');
    if (messagesContainer.children.length === 0) {
      addChatMessage(
        `Hello! 👋 I'm your SkyLine Airways assistant. I can help you with:\n\n` +
        `• Searching for flights\n` +
        `• Booking tickets\n` +
        `• Checking booking status\n` +
        `• Managing your bookings\n` +
        `• Answering questions about our services\n\n` +
        `How can I assist you today?`,
        'bot'
      );
    }
  } else {
    container.classList.add('hidden');
    button.classList.remove('active');
    button.innerHTML = '💬';
  }
}

function addChatMessage(text, sender) {
  const messagesContainer = document.getElementById('chatWidgetMessages');
  const message = document.createElement('div');
  message.className = `chat-message ${sender}`;
  message.textContent = text;
  messagesContainer.appendChild(message);

  // Scroll to bottom
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function showTypingIndicator() {
  const messagesContainer = document.getElementById('chatWidgetMessages');
  const indicator = document.createElement('div');
  indicator.className = 'chat-message bot';
  indicator.id = 'typingIndicator';
  indicator.innerHTML = `
    <div class="chat-typing-indicator">
      <div class="chat-typing-dot"></div>
      <div class="chat-typing-dot"></div>
      <div class="chat-typing-dot"></div>
    </div>
  `;
  messagesContainer.appendChild(indicator);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function removeTypingIndicator() {
  const indicator = document.getElementById('typingIndicator');
  if (indicator) {
    indicator.remove();
  }
}

async function sendChatMessage() {
  const input = document.getElementById('chatWidgetInput');
  const message = input.value.trim();

  if (!message) return;

  // Add user message
  addChatMessage(message, 'user');
  input.value = '';

  // Show typing indicator
  showTypingIndicator();

  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        session_id: chatWidgetSessionId,
        token: state.authToken
      })
    });

    const data = await response.json();

    // Save session ID
    if (data.session_id && !chatWidgetSessionId) {
      chatWidgetSessionId = data.session_id;
      localStorage.setItem('chat_widget_session_id', chatWidgetSessionId);
    }

    // Remove typing indicator
    removeTypingIndicator();

    // Add bot response
    addChatMessage(data.response, 'bot');

  } catch (error) {
    removeTypingIndicator();
    addChatMessage('Sorry, I\'m having trouble connecting. Please try again.', 'bot');
    console.error('Chat error:', error);
  }
}

// ===================================
// CHAT AGENT ACCESS
// ===================================

function openChatAgent() {
  // Check if user is logged in
  if (!state.user || !state.authToken) {
    showNotification('Please login to access the chat agent', 'warning');
    navigateTo('auth');
    return;
  }

  // User is authenticated, open chat agent in new tab
  window.open('TEMPLETE/chat.HTML', '_blank');
}
