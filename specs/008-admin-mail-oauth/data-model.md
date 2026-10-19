# Data model

Existing JSON mail configuration retains gmail_enabled, enable_agent_selection, gmail_sender, gmail_recipient, admin_phone_number and encrypted Google credentials/tokens. gmail_auth_type is always oauth2 for new saves and settings reads. Existing legacy values cannot select SMTP at delivery time. Successful mail settings saves delete gmail_password, gmail_smtp_server and gmail_smtp_port. There is no database schema change. Existing user_google_accounts and OAuth-state lifecycle remain unchanged.
