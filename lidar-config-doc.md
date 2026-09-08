# LiDAR Connection and Recording Procedure

**Blickfeld Qb2 – Setup, Web Interface Access and Data Recording**

AE3S Lab, University of Luxembourg
Author: Ruba Egbaria
Version 1.0 – September 2026

---

## 1. Purpose

This document describes the step-by-step procedure for physically connecting the LiDAR sensor, establishing network communication between the sensor and a laptop, providing the sensor with internet access through a mobile hotspot, accessing the sensor's web interface, and recording a scene. It is intended for lab members who need to operate the sensor independently.

## 2. Required Equipment

| Item | Notes |
|---|---|
| LiDAR sensor (Blickfeld Qb2) | With its Ethernet/PoE cable |
| Network switch with PoE ports | Powers the sensor and links it to the laptop |
| One Ethernet cable | For the laptop |
| Laptop (Windows) | With an Ethernet port or USB-Ethernet adapter and Wi-Fi |
| Smartphone with mobile hotspot | Provides internet access to the switch/sensor |

### Note: The LiDAR, switch and an ethernet cable already available in the AE3S lab.

## 3. Physical Connection

1. Plug the switch into mains power and switch it on.
2. Connect the LiDAR to the switch using the ethernet cable on the LiDAR. The cable **must** be plugged into one of the switch's **PoE ports**, as the sensor is powered through the same cable.
3. Connect the laptop to the switch using a second Ethernet cable. This link is used both for internet sharing (Section 5) and for accessing the sensor's web interface.

<img width="1200" height="1600" alt="image" src="https://github.com/user-attachments/assets/72c9e8fc-50ee-4530-8876-0690691b05bf" />

4. Confirm that the **PoE indicator LED** on the port used by the LiDAR turns **green**. This indicates that the sensor is receiving power.
5. Confirm that the link LED on the laptop's port is active **orange**.

## 4. Laptop Ethernet Configuration (Static IPv4)

The Ethernet adapter on the laptop must be set to a manual (static) IPv4 configuration so that it acts as the gateway for the sensor.

1. Open **Settings → Network & Internet → Ethernet** and select the adapter connected to the switch.
2. Under **IP assignment**, click **Edit** and set the following values:

| Parameter | Value |
|---|---|
| IP assignment | Manual (IPv4 enabled) |
| IPv4 address | `192.168.137.1` |
| IPv4 subnet mask | `255.255.255.0` |

3. Under **DNS server assignment**, click **Edit** and set:

| Parameter | Value |
|---|---|
| DNS server assignment | Manual |
| Preferred IPv4 DNS | `192.168.137.1` |

4. Save the settings. The adapter properties should now match the configuration shown below.

<img width="2227" height="1260" alt="image" src="https://github.com/user-attachments/assets/b277dbbe-6870-48da-bc02-e9f238236d86" />

## 5. Providing Internet Access via Mobile Hotspot

The sensor and the switch have no direct internet access. Internet is provided by sharing the laptop's Wi-Fi connection (from a phone hotspot) to the Ethernet adapter.

1. Enable the **mobile hotspot** on the smartphone.
2. On the laptop, connect to the phone's hotspot over **Wi-Fi**.
3. Press **Windows + R**, type `ncpa.cpl` and press **Enter** to open the *Network Connections* window.
4. Right-click the **Wi-Fi** adapter and select **Properties**.
5. Open the **Sharing** tab.
6. Tick **"Allow other network users to connect through this computer's Internet connection"**.
7. In the **Home networking connection** drop-down, select the Ethernet adapter connected to the switch (typically labelled **Ethernet 2**).
8. Click **OK** to apply.

<img width="852" height="495" alt="image" src="https://github.com/user-attachments/assets/1278a9b3-02b7-4f4a-a218-1de20fba839c" />

<img width="1770" height="605" alt="image" src="https://github.com/user-attachments/assets/1981a4d3-7d5e-4e3d-ac99-1a0de59afdad" />

<img width="785" height="999" alt="image" src="https://github.com/user-attachments/assets/d19f1718-9ea5-44bf-88cf-83b6b3ccedd5" />


Internet Connection Sharing (ICS) is now active. The laptop assigns addresses in the `192.168.137.x` range to devices on the Ethernet side, including the LiDAR.

## 6. Identifying the LiDAR IP Address

Once sharing is enabled, the sensor receives a new IP address from the laptop. This address must be identified before the web interface can be opened.

1. Press **Windows + R**, type `cmd` and press **Enter**.
2. Run the following command:

```
arp -a
```

3. In the output, locate the entry under the interface `192.168.137.1`. The LiDAR appears as an address of the form:

```
192.168.137.X
```

where `X` is a value between 2 and 254.

<img width="1237" height="1356" alt="image" src="https://github.com/user-attachments/assets/436b453e-d120-4247-855a-d0c9450e3dde" />

**Notes**

- If the entry does not appear immediately, wait 20–30 seconds and run the command again; the sensor may still be booting.
- The address may change between sessions. Always repeat this step after reconnecting the sensor.
- The physical (MAC) address column can be used to confirm which entry belongs to the LiDAR.

## 7. Accessing the Web Interface

1. Open **Google Chrome**.
2. In the address bar, enter the IP address identified in Section 6, for example:

```
http://192.168.137.X
```

3. The LiDAR web interface loads. When prompted, enter the access password:

```
usb25model@lu
```

4. After authentication the interface is active and the sensor status is displayed.

<img width="1311" height="929" alt="image" src="https://github.com/user-attachments/assets/d91aba19-c5e7-445a-818d-cafba05ff9db" />

## 8. Scene Setup and Recording

With the interface open, configure the sensor before recording:

1. **Sensor location** – Set the mounting position and orientation of the LiDAR so that the point cloud is aligned with the physical scene.
2. **Background** – Capture or define the static background of the scene. This allows the sensor to separate moving objects from fixed structures.
3. **Zones** – Define one or more monitoring zones according to the experiment requirements (e.g. the area in which people are to be counted or tracked).
4. **Recording** – Start the recording from the interface and run it for the required duration.
5. **Stop** the recording when the session is complete.

<img width="753" height="551" alt="image" src="https://github.com/user-attachments/assets/71144a3b-f617-4431-b259-6586cb1eb4c4" />

## A preview of the final set-up

<img width="1200" height="1600" alt="image" src="https://github.com/user-attachments/assets/1a7a785e-45d6-4b61-b8d6-fded11073964" />


When the recording is stopped, the interface automatically prepares and **downloads a file** to the laptop containing all recorded data and the associated metadata for the session.

<img width="711" height="641" alt="image" src="https://github.com/user-attachments/assets/879d5661-32ab-4661-8042-5bd82e62bb00" />

<img width="1455" height="940" alt="image" src="https://github.com/user-attachments/assets/ed0b19ad-85f1-40e7-a654-ce0075b90252" />

## 9. Shutdown

1. Stop any running recording and ensure the download has completed.
2. Close the web interface.
3. Optionally disable Internet Connection Sharing (Section 5, step 6) and the phone hotspot.
4. Power off the switch. The LiDAR is powered down automatically through PoE.

## 10. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| PoE LED not green | LiDAR not on a PoE port, or switch unpowered | Move the cable to a PoE port; check the switch power |
| LiDAR not listed in `arp -a` | Sharing not applied, or sensor still booting | Re-check Section 5; wait 30 s and retry |
| Web interface does not load | Wrong IP, or laptop IP not `192.168.137.1` | Re-run `arp -a`; verify Section 4 settings |
| No internet on the sensor | Hotspot not shared to the correct adapter | Ensure "Ethernet 2" is selected in the Sharing tab |
| Password rejected | Typing error | Re-enter `usb25model@lu` exactly |

---
