document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('login-form');
  const message = document.getElementById('login-error');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    message.textContent = '';
    try {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: form.elements.email.value,
          password: form.elements.password.value,
        }),
      });
      if (!response.ok) throw new Error('Sign-in failed. Check your email and password.');
      form.elements.password.value = '';
      window.location.assign('/portal/');
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
});
