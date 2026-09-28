import os
import sys
import json
import time

def get_logitech_hidraw_devices():
    devices = []
    for entry in sorted(os.listdir('/sys/class/hidraw/')):
        path = f"/sys/class/hidraw/{entry}/device"
        uevent_path = os.path.join(path, 'uevent')
        if not os.path.exists(uevent_path):
            continue
        try:
            with open(uevent_path, 'r') as f:
                content = f.read()
            
            vendor = None
            product = None
            name = ""
            for line in content.splitlines():
                if line.startswith('HID_ID='):
                    parts = line.split('=')[1].split(':')
                    if len(parts) >= 3:
                        vendor = parts[1].strip().lower().lstrip('0')
                        product = parts[2].strip().lower().lstrip('0')
                elif line.startswith('HID_NAME='):
                    name = line.split('=')[1]
            
            if vendor == '46d':
                devices.append({
                    'dev_path': f"/dev/{entry}",
                    'name': name,
                    'vendor': '046d',
                    'product': product
                })
        except Exception:
            pass
    # Prioritize dedicated mouse/keyboard devices over generic USB receiver nodes
    devices.sort(key=lambda d: 1 if 'receiver' in d['name'].lower() else 0)
    return devices

def query_feature_index(fd, device_idx, feature_id, sw_id=0x01):
    expected_fn_sw = (0x0 << 4) | (sw_id & 0x0f)
    cmd = bytearray([0x10, device_idx, 0x00, expected_fn_sw, (feature_id >> 8) & 0xff, feature_id & 0xff, 0x00])
    try:
        os.write(fd, cmd)
    except Exception:
        return None

    for _ in range(25):
        time.sleep(0.02)
        try:
            data = os.read(fd, 20)
            if data and (data[0] == 0x10 or data[0] == 0x11):
                if len(data) >= 5 and data[2] == 0x00 and data[3] == expected_fn_sw:
                    feat_idx = data[4]
                    return feat_idx if feat_idx > 0 else None
        except BlockingIOError:
            continue
        except Exception:
            break
    return None

def query_battery(dev_path, device_idx):
    try:
        fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
    except Exception:
        return None

    try:
        # Flush read buffer
        try:
            while os.read(fd, 20): pass
        except Exception:
            pass

        # 1. Try Unified Battery (0x1004) with sw_id=0x01
        feature_idx = query_feature_index(fd, device_idx, 0x1004, sw_id=0x01)
        if feature_idx and feature_idx > 0:
            sw_id = 0x02
            expected_fn_sw = (0x1 << 4) | (sw_id & 0x0f)
            bat_cmd = bytearray([0x10, device_idx, feature_idx, expected_fn_sw, 0x00, 0x00, 0x00])
            try:
                os.write(fd, bat_cmd)
            except Exception:
                return None

            for _ in range(25):
                time.sleep(0.02)
                try:
                    data = os.read(fd, 20)
                    if data and (data[0] == 0x10 or data[0] == 0x11):
                        if len(data) >= 7 and data[2] == feature_idx and data[3] == expected_fn_sw:
                            percentage = data[4]
                            status_code = data[6]
                            # In HID++ 0x1004 (Unified Battery):
                            # 0x00: Discharging
                            # 0x01: Charging
                            # 0x02: ChargingNearlyFull
                            # 0x03: Full (charge complete on charger)
                            # 0x04: ChargingSlow
                            # 0x05-0x07: Errors
                            is_charging = status_code in [0x01, 0x02, 0x03, 0x04]
                            return {
                                'percentage': percentage,
                                'status_code': status_code,
                                'is_charging': is_charging,
                                'protocol': 'Unified Battery (0x1004)'
                            }
                except BlockingIOError:
                    continue
                except Exception:
                    break
            # Do not fall back to 0x1000 if 0x1004 was already identified on this device
            return None

        # 2. Try Fallback: Legacy Battery Status (0x1000) with sw_id=0x03
        try:
            while os.read(fd, 20): pass
        except Exception:
            pass

        feature_idx = query_feature_index(fd, device_idx, 0x1000, sw_id=0x03)
        if feature_idx and feature_idx > 0:
            sw_id = 0x04
            expected_fn_sw = (0x0 << 4) | (sw_id & 0x0f)
            bat_cmd = bytearray([0x10, device_idx, feature_idx, expected_fn_sw, 0x00, 0x00, 0x00])
            try:
                os.write(fd, bat_cmd)
            except Exception:
                return None

            for _ in range(25):
                time.sleep(0.02)
                try:
                    data = os.read(fd, 20)
                    if data and (data[0] == 0x10 or data[0] == 0x11):
                        if len(data) >= 7 and data[2] == feature_idx and data[3] == expected_fn_sw:
                            percentage = data[4]
                            status_code = data[6]
                            # In HID++ 0x1000 (Battery Status):
                            # 0x00: Discharging
                            # 0x01: Recharging
                            # 0x02: Almost full
                            # 0x03: Full
                            # 0x04: Slow recharge
                            # 0x05: Invalid battery
                            is_charging = status_code in [0x01, 0x02, 0x03, 0x04]
                            return {
                                'percentage': percentage,
                                'status_code': status_code,
                                'is_charging': is_charging,
                                'protocol': 'Battery Status (0x1000)'
                            }
                except BlockingIOError:
                    continue
                except Exception:
                    break

    finally:
        os.close(fd)
    return None

def main():
    devices = get_logitech_hidraw_devices()
    if not devices:
        print(json.dumps({"success": False, "error": "No Logitech HID devices found"}))
        return

    for dev in devices:
        for idx in [0x01, 0x02, 0xff]:
            res = query_battery(dev['dev_path'], idx)
            if res:
                status_str = "charging" if res['is_charging'] else "discharging"
                out = {
                    "success": True,
                    "percentage": res['percentage'],
                    "status": status_str,
                    "status_code": res['status_code'],
                    "protocol": res['protocol'],
                    "device_name": dev['name'],
                    "dev_path": dev['dev_path']
                }
                print(json.dumps(out))
                return

    print(json.dumps({"success": False, "error": "Logitech device found but did not respond to battery queries"}))

if __name__ == '__main__':
    main()
