import os
import sys
import sqlite3

# Ensure serviceBot is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serviceBot.db.connection import get_db_connection
from serviceBot.api.portal import sync_services_to_kb

SERVICES_DATA = [
    (
        "Standard System Inspection",
        "Full system diagnostic check, filter replacement, fluid top-offs, pressure check, and a complimentary courtesy inspection.",
        "$79 - $119",
        45,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        0, # req_issue_description (routine maintenance, no issue needed)
        1  # req_location
    ),
    (
        "Component Repair & Pad Replacement",
        "Full system diagnostic check, premium component replacement, rotor/part resurfacing or replacement, and safety checks.",
        "$199 - $399",
        90,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description
        1  # req_location
    ),
    (
        "Climate Control Service & System Diagnostic",
        "A/C and heating system performance test, pressure testing, visual inspection of lines and components, leak detection, and full refrigerant recharge.",
        "$99 - $249",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description
        1  # req_location
    ),
    (
        "Precision System Alignment & Calibration",
        "Precision computerized alignment adjusting operating angles to original manufacturer specifications.",
        "$119 - $149",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        0, # req_issue_description
        1  # req_location
    ),
    (
        "Scheduled Maintenance (Periodic)",
        "Comprehensive periodic maintenance conforming to manufacturer warranty standards, including fluids flush, cabin/air filters, and multi-point safety inspections.",
        "$249 - $599",
        120,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        0, # req_issue_description
        1  # req_location
    ),
    (
        "System Error Light Diagnostic",
        "Full scanning and diagnostics of system sensors, freeze-frame data analysis, and visual checks of affected components.",
        "$99 - $149",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description
        1  # req_location
    ),
    (
        "Fluid Exchange & Service",
        "Complete exchange of old system fluid with high-quality spec fluid, cleaning of fluid reservoir, and replacement of filter.",
        "$189 - $299",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        0, # req_issue_description
        1  # req_location
    ),
    (
        "Suspension & Structural Inspection",
        "Inspection and replacement of worn struts, shock absorbers, links, and bushings to restore control and safety.",
        "$299 - $899",
        120,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description
        1  # req_location
    ),
    (
        "Power & Electrical System Service",
        "Power supply voltage and diagnostic check, terminal cleaning, and professional component installation.",
        "$149 - $249",
        30,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        0, # req_issue_description
        1  # req_location
    ),
    (
        "Cooling System Flush & Diagnostic",
        "Performance inspection, pressure testing for leaks, full drainage of old coolant, and refill with fresh coolant.",
        "$129 - $199",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description
        1  # req_location
    ),
    (
        "Air Filtration System",
        "Inspection and replacement of intake air filters and passenger cabin air filters to maintain interior air quality.",
        "$49 - $99",
        30,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Electronics & Ignition Service",
        "Testing and replacement of starter motors, alternators, power cables, and related electronics.",
        "$249 - $599",
        90,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Auto Repair Estimates",
        "Comprehensive visual and system inspections to draft transparent, detailed repair estimates for collision, wear-and-tear, or custom parts repair.",
        "Free / TBD",
        30,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Computer Diagnostic",
        "Advanced modular diagnostic scan interfacing with onboard vehicle controllers to pinpoint issues in engine, body control, transmission, and comfort modules.",
        "$119 - $189",
        60,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Courtesy Inspection",
        "Complimentary multi-point visual inspection of brakes, tires, fluids, filters, belts, and safety components, complete with a digital health report.",
        "$0",
        20,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Drivetrain Repair & Service",
        "Service and replacement of constant velocity (CV) axles, driveshafts, differentials, transfer cases, and universal joints.",
        "$199 - $699",
        90,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Electrical System Repair",
        "Diagnosing and fixing automotive electrical issues including wiring harnesses, fuses, power windows, locks, lighting, and dashboard controls.",
        "$119 - $499",
        90,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Engine Services (Spark Plugs, Belts, Gaskets)",
        "Minor and major engine repairs, spark plug replacements, timing belts, cylinder head gasket work, and manifold service.",
        "$149 - $1200+",
        120,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "European Vehicle Services",
        "Specialized diagnostics, parts, and service catering to European brands such as BMW, Mercedes-Benz, Audi, Volkswagen, Volvo, and Jaguar.",
        "Varies",
        90,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Exhaust System & Muffler Repair",
        "Inspection and replacement of exhaust pipes, mufflers, oxygen sensors, exhaust manifolds, and catalytic converters to ensure clean emissions.",
        "$149 - $599",
        60,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Extended Warranty Service Claim Repairs",
        "Assistance in coordinating diagnosis, estimates, and covered repair work directly with all major extended warranty providers.",
        "Varies",
        60,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Fleet Services (Commercial Accounts)",
        "Custom scheduled preventative maintenance, repairs, and inspections for business, commercial, and municipality fleet vehicles.",
        "Varies",
        60,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Fuel System Service (Injectors & Cleaning)",
        "Fuel injection cleaning, fuel filter replacement, and diagnostic tests on fuel pumps and lines to restore MPG and throttle response.",
        "$129 - $249",
        60,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Power Steering Fluid Exchange & Repair",
        "Power steering system flush, pump replacement, and steering gear rack-and-pinion diagnostics and repairs.",
        "$119 - $599",
        60,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Pre-Purchase Inspection",
        "Thorough bumper-to-bumper pre-purchase inspection of safety, mechanical, and aesthetic elements before purchasing a pre-owned vehicle.",
        "$119 - $179",
        60,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Tire Rotation & Balancing",
        "Rotating tires, performing precision computer wheel balancing, and adjusting pressure to prolong tread life and restore smooth riding.",
        "$39 - $89",
        30,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Tune-Ups & Spark Plug Service",
        "Replacement of spark plugs, inspection of ignition coils and wires, and throttle body cleaning to ensure smooth idling and peak combustion efficiency.",
        "$149 - $299",
        60,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Tire Replacement & Installation",
        "Professional mounting, computer balancing, and installation of brand new tires tailored to your vehicle specifications.",
        "$150 - $300 per tire",
        60,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Windshield Wiper Blade Replacement",
        "Replacement of worn front or rear windshield wiper blades with premium, high-durability blades to ensure clear visibility.",
        "$29 - $59",
        15,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Serpentine Belt Replacement",
        "Inspection and replacement of the serpentine accessory drive belt to prevent engine accessory failures and breakdowns.",
        "$99 - $159",
        30,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Headlight & Bulb Replacement",
        "Replacement of burned-out exterior bulbs including headlights, high beams, fog lights, brake lights, and turn signals.",
        "$29 - $79",
        20,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Spark Plug Replacement",
        "Complete set of new premium spark plugs installed to restore clean combustion, improve fuel economy, and resolve engine misfires.",
        "$99 - $249",
        45,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Radiator & Cooling System Repair",
        "Diagnosis and repair of cooling system leaks, radiator replacement, thermostat replacement, and cooling fan repairs.",
        "$299 - $699",
        120,
        1,
        1,
        1,
        1,
        1
    ),
    (
        "Callback / Phone Consultation",
        "A 15-minute scheduled phone consultation or callback request with a service advisor or technician.",
        "$0",
        15,
        1,
        1,
        1,
        0,
        1
    )
]

def main():
    print("Seeding Davidson Car Care service catalog...")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Insert default catalog items if they do not already exist (preserving user-added catalog items)
        for svc in SERVICES_DATA:
            name, desc, price, dur, r_name, r_phone, r_veh, r_issue, r_loc = svc
            cursor.execute("""
                INSERT INTO services (
                    name, description, price_range, duration_minutes, 
                    req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location
                )
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM services WHERE LOWER(name) = LOWER(%s)
                );
            """, (name, desc, price, dur, bool(r_name), bool(r_phone), bool(r_veh), bool(r_issue), bool(r_loc), name))
            
        conn.commit()
        
    print("Database seeding completed.")
    
    print("Synchronizing updated service catalog to RAG Knowledge Base...")
    try:
        sync_services_to_kb()
        print("Knowledge Base synchronized successfully.")
    except Exception as e:
        print(f"Error synchronizing knowledge base: {str(e)}")

if __name__ == "__main__":
    main()
