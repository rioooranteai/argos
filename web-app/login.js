// Login page: show the message for ?error=<CODE> (kept out of the HTML for the Content-Security-Policy).
(function () {
    var messages = {
        DOMAIN_NOT_ALLOWED: "This Google account is not allowed to sign in.",
        EMAIL_NOT_VERIFIED: "Your Google email is not verified.",
        USER_INACTIVE: "Your account has been deactivated. Contact the admin.",
        RATE_LIMITED: "Too many sign-in attempts. Try again in a minute.",
        GOOGLE_ACCESS_DENIED: "Sign-in was cancelled or blocked by Google. Try again, or ask the admin to allow this account.",
        GOOGLE_SIGN_IN_FAILED: "Google sign-in did not complete. Please try again."
    };
    var code = new URLSearchParams(window.location.search).get("error");
    if (!code) return;
    var el = document.getElementById("loginError");
    el.textContent = messages[code] || "Sign-in failed. Please try again.";
    el.hidden = false;
})();
