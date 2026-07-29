from serviceBot.db.queries import (
    update_customer_opt_in,
    add_sms_whitelist,
    get_or_create_sms_conversation,
    add_sms_message,
    update_sms_conversation_state
)
from serviceBot.services.sms_classifier import process_inbound_sms

def seed_sample_data():
    print("[seed_sample_sms] Seeding sample SMS threads and whitelist numbers...")
    
    # 1. Whitelist numbers
    add_sms_whitelist("+15550192831", "Sarah Johnson (Test)", twilio_verified=True)
    add_sms_whitelist("+15550199876", "David Smith (Test)", twilio_verified=True)
    add_sms_whitelist("+15550195555", "Emily Davis (Test)", twilio_verified=True)

    # 2. Thread 1: Needs Attention (HANDOFF_REQUIRED)
    conv1 = get_or_create_sms_conversation("+15550192831")
    add_sms_message(conv1["id"], "inbound", "customer", "Sarah Johnson", "Hi, can I bring my Honda Civic in 30 minutes earlier tomorrow?")
    update_sms_conversation_state(conv1["id"], "HANDOFF_REQUIRED")

    # 3. Thread 2: In Progress (IN_PROGRESS)
    conv2 = get_or_create_sms_conversation("+15550199876")
    add_sms_message(conv2["id"], "inbound", "customer", "David Smith", "Is the courtesy shuttle available to drop me off at Springfield Mall?")
    add_sms_message(conv2["id"], "outbound", "agent", "Support Agent", "Yes David! Our shuttle driver John can drop you off right at the main entrance.")
    update_sms_conversation_state(conv2["id"], "IN_PROGRESS")

    # 4. Thread 3: Resolved (RESOLVED)
    conv3 = get_or_create_sms_conversation("+15550195555")
    add_sms_message(conv3["id"], "inbound", "customer", "Emily Davis", "Will my AC repair be covered under warranty?")
    add_sms_message(conv3["id"], "outbound", "agent", "Support Agent", "Yes Emily, factory AC components are covered under your 3-year warranty.")
    update_sms_conversation_state(conv3["id"], "RESOLVED")



    print("[seed_sample_sms] Sample data seeded successfully!")


if __name__ == "__main__":
    seed_sample_data()
