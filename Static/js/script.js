/* 1. -------------------------NAVIGATION & LAYOUT SCRIPTS -------------------------------*/

// --- Sticky Navbar Effect ---
// Changes the navbar background from transparent to white when scrolling down
window.addEventListener('scroll', () => {
    const navbar = document.getElementById('navbar');
    // Check if user scrolled down more than 20 pixels
    if (window.scrollY > 20) {
        navbar.classList.add('bg-white/95', 'shadow-md');
        navbar.classList.remove('border-white/20');
    } else {
        navbar.classList.remove('bg-white/95', 'shadow-md');
        navbar.classList.add('border-white/20');
    }
});

// --- Mobile Menu Logic (Slide-Over Drawer) ---
// Handles opening and closing the side menu on mobile screens
const openBtn = document.getElementById('mobile-menu-btn');
const closeBtn = document.getElementById('close-menu-btn');
const mobileMenu = document.getElementById('mobile-menu');
const overlay = document.getElementById('mobile-overlay');
const mobileLinks = document.querySelectorAll('.mobile-link');

// Function to Open Menu
function openMenu() {
    mobileMenu.classList.remove('translate-x-full'); // Slide menu in
    overlay.classList.remove('hidden');              // Show dark overlay
    setTimeout(() => {
        overlay.classList.remove('opacity-0');       // Fade overlay in smoothly
    }, 10);
    document.body.style.overflow = 'hidden';         // Stop background from scrolling
}

// Function to Close Menu
function closeMenu() {
    mobileMenu.classList.add('translate-x-full');    // Slide menu out
    overlay.classList.add('opacity-0');              // Fade overlay out
    setTimeout(() => {
        overlay.classList.add('hidden');             // Hide overlay after fade
    }, 300);
    document.body.style.overflow = 'auto';           // Re-enable scrolling
}

// Event Listeners for Menu
if (openBtn) openBtn.addEventListener('click', openMenu);
if (closeBtn) closeBtn.addEventListener('click', closeMenu);
if (overlay) overlay.addEventListener('click', closeMenu);

// Close menu automatically when a user clicks a link inside it
mobileLinks.forEach(link => {
    link.addEventListener('click', closeMenu);
});


/* 2. ----------------------------SHOPPING CART FUNCTIONALITY ------------------------------*/

// --- 'Add to Cart' Animation & Counter ---
const addToCartBtns = document.querySelectorAll('.fa-plus');
let count = 0;
addToCartBtns.forEach(btn => {
    // Listener for the button container
    btn.parentElement.addEventListener('click', function () {

        // 1. Visual Feedback (Change Plus icon to Checkmark)
        this.innerHTML = '<i class="fa-solid fa-check"></i>';
        this.classList.remove('bg-white', 'text-ayur-dark');
        this.classList.add('bg-ayur-primary', 'text-white'); // Turn green

        // 2. Update Cart Counter Number
        count++;
        const badge = document.querySelector('a i.fa-basket-shopping + span');
        if (badge) badge.innerText = count;

        // 3. Reset Button back to normal after 2 seconds
        setTimeout(() => {
            this.innerHTML = '<i class="fa-solid fa-plus"></i>';
            this.classList.add('bg-white', 'text-ayur-dark');
            this.classList.remove('bg-ayur-primary', 'text-white');
        }, 2000);
    });
});


/* -----------------------3. REGISTRATION FORM SCRIPTS ------------------------------*/

document.addEventListener('DOMContentLoaded', function () {
    // --- Form Styling ---
    const inputs = document.querySelectorAll('input, select');
    inputs.forEach(input => {
        input.classList.add('custom-input', 'w-full', 'px-4', 'py-3', 'border', 'border-gray-200', 'rounded-lg', 'text-gray-700', 'focus:outline-none', 'text-sm');

        if (input.type === 'password' || input.name === 'email' || input.name === 'phone') {
            input.classList.add('pl-10');
        }
    });

    // --- Alert Message Auto-Hide ---
    // Finds Django success/error messages and hides them after 5 seconds
    const message = document.querySelector('.bg-green-50, .bg-red-50');
    if (message) {
        setTimeout(() => {
            message.style.transition = 'opacity 0.5s ease'; // Smooth fade out
            message.style.opacity = '0';
            setTimeout(() => message.remove(), 500); // Remove from DOM
        }, 5000);
    }
});


/* 4. LOGIN FORM SCRIPTS */

// --- Password Visibility Toggle ---
// Switches the password field between 'password' (hidden) and 'text' (visible)
function togglePassword() {
    const passwordField = document.getElementById('password-field');
    const eyeIcon = document.getElementById('eye-icon');

    if (passwordField && eyeIcon) {
        if (passwordField.type === 'password') {
            // Show Password
            passwordField.type = 'text';
            eyeIcon.classList.remove('fa-eye');
            eyeIcon.classList.add('fa-eye-slash');
        } else {
            // Hide Password
            passwordField.type = 'password';
            eyeIcon.classList.remove('fa-eye-slash');
            eyeIcon.classList.add('fa-eye');
        }
    }
}
