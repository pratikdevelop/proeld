# 📘 README: ProELD Driver Tablet

**ProELD** is a high-performance, tablet-optimized interface designed for commercial truck drivers to manage compliance with FMCSA (Federal Motor Carrier Safety Administration) Hours of Service (HOS) regulations.

This web-based application provides real-time telemetry integration, automated duty logging, and a dedicated DOT Inspection mode for roadside safety officers.

---

## 🚛 Key Compliance Features

This application helps drivers and motor carriers adhere to **49 CFR Part 395** requirements:

* **11-Hour Driving Limit**
  Real-time tracking of the maximum 11 hours of driving permitted within a duty window.

* **14-Hour Driving Window**
  A consecutive 14-hour countdown begins when any work starts. After this period, driving is prohibited until 10 consecutive hours off-duty are taken.

* **30-Minute Rest Break**
  Automatic monitoring of the required 30-minute consecutive break after 8 cumulative hours of driving.

* **60/70-Hour Weekly Limits**
  Supports both 7-day and 8-day rolling ("floating") periods to prevent over-exhaustion across multiple duty days.

* **34-Hour Restart**
  Visual indicators show when a driver has completed the required 34 consecutive hours off-duty to reset their weekly clock.

* **Electronic Logging Device (ELD)**
  An integrated digital Record of Duty Status (RODS) that replaces traditional paper logs.

---

## ⚙️ Technical Integration

* **FMCSA Auto-Duty Logic**
  Integrated speed monitoring (simulated via WebSocket) automatically switches the status to **"Driving"** when the vehicle exceeds 5 MPH, ensuring accurate HOS records.

* **Log Graph Grid**
  A dynamic HTML5 Canvas engine renders a compliant daily log grid, visualizing duty status transitions over a 24-hour period.

* **DOT Inspection Mode**
  A secure, locked **"Officer View"** hides private driver data while providing immediate access to required compliance logs during roadside inspections.

* **Offline-First Architecture**
  Uses LocalStorage and IndexedDB to cache log data during cellular dead zones and automatically syncs with the fleet manager once connectivity is restored.

* **Electronic DVIR (eDVIR)**
  A digitized Driver Vehicle Inspection Report for certifying vehicle safety before and after trips.

---

## 🚀 Quick Start

1. **Dashboard**
   Monitor HOS clocks, remaining drive time, and real-time location.

2. **Duty Status**
   Use the top bar to switch between:

   * Off-Duty
   * Sleeper Berth
   * Driving *(auto-locked while the vehicle is in motion)*
   * On-Duty

3. **Logs**
   View your automated 24-hour log graph and export data for inspections.

4. **Inspection Mode**
   Click the **DOT Inspection** button when requested by law enforcement to lock the device into a compliant review mode.

---

## ⚠️ Disclaimer

This software is intended as a guidance tool and does not replace the driver’s responsibility to understand and comply with all applicable FMCSA regulations.

---
