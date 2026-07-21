import os
import sys
import sqlite3

# Ensure serviceBot is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serviceBot.db.connection import get_db_connection
from serviceBot.api.portal import sync_services_to_kb

SERVICES_DATA = [
    (
        "Oil Change (Full Synthetic)",
        "Full synthetic motor oil replacement, premium filter replacement, fluid top-offs, tire pressure check, and a complimentary courtesy inspection.",
        "$79 - $119",
        45,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        0, # req_issue_description (routine maintenance, no issue needed)
        1  # req_location
    ),
    (
        "Brake Repair & Pad Replacement",
        "Full braking system diagnostic check, premium ceramic/semi-metallic brake pad replacement, rotor resurfacing or replacement, and caliper checks.",
        "$199 - $399 per axle",
        90,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description (needs symptoms like squealing or grinding)
        1  # req_location
    ),
    (
        "A/C Service & System Diagnostic",
        "A/C system performance test, pressure testing, visual inspection of lines and components, leak detection using UV dye, and full refrigerant recharge.",
        "$99 - $249",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description (needs symptoms like blowing warm air)
        1  # req_location
    ),
    (
        "Wheel Alignment (4-Wheel)",
        "Precision computerized alignment adjusting front and rear caster, camber, and toe angles to original manufacturer specifications.",
        "$119 - $149",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        0, # req_issue_description (preventative maintenance)
        1  # req_location
    ),
    (
        "Manufacturer Scheduled Maintenance (30k/60k/90k)",
        "Comprehensive mileage-specific maintenance conforming to manufacturer warranty standards, including fluids flush, cabin/air filters, spark plugs check, and multi-point safety inspections.",
        "$249 - $599",
        120,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details (highly important to know make/model/year)
        0, # req_issue_description
        1  # req_location
    ),
    (
        "Check Engine Light Diagnostic",
        "Full scanning and diagnostics of the vehicle OBD-II system, sensor testing, freeze-frame data analysis, and visual checks of affected components.",
        "$99 - $149",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description (needs warning light symptoms or descriptions)
        1  # req_location
    ),
    (
        "Transmission Fluid Exchange",
        "Complete exchange of old transmission fluid with high-quality OEM spec fluid, cleaning of transmission pan, and replacement of transmission filter (if applicable).",
        "$189 - $299",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        0, # req_issue_description
        1  # req_location
    ),
    (
        "Suspension Repair (Shocks & Struts)",
        "Inspection and replacement of worn front and rear struts, shock absorbers, sway bar links, and bushings to restore ride control and safety.",
        "$299 - $899",
        120,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description (requires symptoms like bouncing, pulling, or noise)
        1  # req_location
    ),
    (
        "Battery Replacement & System Test",
        "Automotive battery voltage and cold-cranking amps diagnostic check, cleaning of battery terminals, and professional installation of a new premium battery.",
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
        "Radiator performance inspection, pressure testing for leaks, full drainage of old coolant, flush of heater core/radiator, and refill with fresh OEM coolant.",
        "$129 - $199",
        60,
        1, # req_customer_name
        1, # req_phone_number
        1, # req_vehicle_details
        1, # req_issue_description (requires symptoms like overheating or coolant leaks)
        1  # req_location
    ),
    (
        "Air Filtration (Engine & Cabin)",
        "Inspection and replacement of engine intake air filters and passenger cabin air filters to maintain engine performance and interior air quality.",
        "$49 - $99",
        30,
        1,
        1,
        1,
        0,
        1
    ),
    (
        "Alternator & Starter Service",
        "Testing and replacement of starter motors, alternators, battery cables, and related ignition/charging system electronics.",
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
    )
]

def main():
    print("Seeding Test service catalog...")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Clear existing services to replace with correct catalog
        cursor.execute("DELETE FROM services;")
        conn.commit()
        
        for svc in SERVICES_DATA:
            cursor.execute("""
                INSERT INTO services (
                    name, description, price_range, duration_minutes, 
                    req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, svc)
            print(f"Added service: '{svc[0]}'")
            
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
