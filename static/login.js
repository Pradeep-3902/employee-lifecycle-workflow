
"use strict";

/* =========================================================
   EMPLOYEE LIFECYCLE WORKFLOW — LOGIN INTERACTIONS
   File: static/login.js
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
  const passwordInput = document.querySelector("#password");
  const togglePassword = document.querySelector("#toggle-password");

  /* ---------- Password visibility toggle ---------- */

  if (passwordInput && togglePassword) {
    // Set the initial accessibility state.
    togglePassword.setAttribute("type", "button");
    togglePassword.setAttribute("aria-controls", "password");
    togglePassword.setAttribute("aria-pressed", "false");
    togglePassword.setAttribute("aria-label", "Show password");
    togglePassword.textContent = "Show";

    togglePassword.addEventListener("click", () => {
      const reveal = passwordInput.type === "password";

      passwordInput.type = reveal ? "text" : "password";

      togglePassword.textContent = reveal ? "Hide" : "Show";
      togglePassword.setAttribute(
        "aria-label",
        reveal ? "Hide password" : "Show password"
      );
      togglePassword.setAttribute(
        "aria-pressed",
        String(reveal)
      );

      // Keep focus in the password field after toggling.
      passwordInput.focus({ preventScroll: true });
    });
  }

  /* ---------- Focus the first useful field ---------- */

  const emailInput = document.querySelector(
    "#email, #username, input[name='email'], input[name='username']"
  );

  if (emailInput && !emailInput.value) {
    emailInput.focus({ preventScroll: true });
  }

  /* ---------- Prevent accidental repeated form submission ---------- */

  const loginForm = document.querySelector(
    ".login-form, #login-form"
  );

  if (loginForm) {
    loginForm.addEventListener("submit", () => {
      const submitButton = loginForm.querySelector(
        "button[type='submit'], input[type='submit']"
      );

      if (submitButton) {
        // Allow the browser to submit the form normally.
        // The submit button is disabled after submission starts.
        submitButton.disabled = true;
        submitButton.setAttribute("aria-busy", "true");
      }
    });
  }
});
