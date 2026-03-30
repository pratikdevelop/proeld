README: ProELD Driver Tablet
ProELD is a high-performance, tablet-optimized interface designed for commercial truck drivers to manage compliance with FMCSA (Federal Motor Carrier Safety Administration) Hours of Service (HOS) regulations. This web-based application provides real-time telemetry integration, automated duty logging, and a dedicated DOT Inspection mode for roadside safety officers.

Key Compliance Features
This application is built to help drivers and motor carriers adhere to 49 CFR Part 395 requirements:

* 
11-Hour Driving Limit: Real-time tracking of the maximum 11 hours of driving permitted within a duty window.

* 
14-Hour Driving Window: A consecutive 14-hour countdown that begins when any work starts, after which driving is prohibited until 10 consecutive hours off-duty are taken.

* 
30-Minute Rest Break: Automatic monitoring of the required 30-minute consecutive break after 8 cumulative hours of driving.

* 
60/70-Hour Weekly Limits: Support for both 7-day and 8-day rolling "floating" periods to prevent over-exhaustion across multiple duty days.

* 
34-Hour Restart: Visual indicators for when a driver has satisfied the 34-consecutive-hour off-duty requirement to reset their weekly clock.

* 
Electronic Logging Device (ELD): An integrated digital record of duty status (RODS) that replaces traditional paper logs.

Technical Integration
* FMCSA Auto-Duty Logic: Integrated speed monitoring (simulated via WebSocket) automatically switches status to "Driving" when the vehicle exceeds 5 MPH to ensure accurate HOS records.
* 
Log Graph Grid: A dynamic HTML5 Canvas engine that renders a compliant daily log grid, visualizing duty status transitions throughout a 24-hour period.

* 
DOT Inspection Mode: A security-locked "Officer View" that hides private driver data while providing immediate access to required compliance logs for roadside inspections.

* Offline First: Utilizing LocalStorage and IndexedDB to cache log data during cellular dead zones, automatically syncing with the fleet manager once a connection is restored.
* Electronic DVIR: A digitized Driver Vehicle Inspection Report (eDVIR) for certifying vehicle safety before and after trips.
Quick Start
1. Dashboard: Monitor HOS clocks, remaining drive time, and real-time location.
2. 
Duty Status: Use the top bar to manually switch between Off-Duty, Sleeper Berth, Driving, and On-Duty (Note: "Driving" is automatically locked when in motion).

3. 
Logs: View your automated 24-hour graph and export data for inspections.

4. Inspection: Click the DOT Inspection button when requested by law enforcement to lock the device into a compliant review mode.

Disclaimer: This software is a guidance tool and does not substitute for the driver's responsibility to understand and comply with all published FMCSA regulations.