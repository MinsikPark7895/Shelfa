import re

with open('/home/user/Shelfa/ros2_ws/src/Doosan-E0509-ROBOTIS-RH-P12-RN-TCP-Bridge/dsr_gripper_tcp/dsr_gripper_tcp/gripper_tcp_bridge.py', 'r') as f:
    content = f.read()

# Replace int.from_bytes
content = content.replace("seq = int.from_bytes(header[4:6], byteorder='big', signed=False)", "seq = struct.unpack('>H', str(header[4:6]))[0]")
content = content.replace("payload_size = int.from_bytes(header[6:8], byteorder='big', signed=False)", "payload_size = struct.unpack('>H', str(header[6:8]))[0]")
content = content.replace("g_goal_current = int.from_bytes(payload[0:2], byteorder='big', signed=False)", "g_goal_current = struct.unpack('>H', str(payload[0:2]))[0]")
content = content.replace("cfg.baudrate = int.from_bytes(payload[0:4], byteorder='big', signed=False)", "cfg.baudrate = struct.unpack('>I', str(payload[0:4]))[0]")
content = content.replace("goal_position = int.from_bytes(payload[0:4], byteorder='big', signed=True)", "goal_position = struct.unpack('>i', str(payload[0:4]))[0]")
content = content.replace("present_current = int.from_bytes(current_reg, byteorder='big', signed=True)", "present_current = struct.unpack('>h', str(current_reg))[0]")

# Replace to_bytes and bytes() in send_response
content = content.replace(
    "header = b\"GP\" + bytes([1, command]) + seq.to_bytes(2, 'big') + len(payload).to_bytes(2, 'big')",
    "header = b\"GP\" + struct.pack('>BBHH', 1, command, seq, len(payload))"
)

# Replace CRC crc ^= packet[i] crash
content = content.replace(
    "packet = struct.pack(\">B\", slave_id) + payload\n                crc = 0xFFFF",
    "packet = bytearray(struct.pack(\">B\", slave_id) + payload)\n                crc = 0xFFFF"
)
content = content.replace(
    "return packet + struct.pack(\"<H\", crc)",
    "return bytes(packet) + struct.pack(\"<H\", crc)"
)

# Encode state payload has to_bytes?
content = content.replace("present_current.to_bytes(2, byteorder='big', signed=True)", "struct.pack('>h', present_current)")
content = content.replace("present_temperature.to_bytes(1, byteorder='big', signed=True)", "struct.pack('>b', present_temperature)")
content = content.replace("present_velocity.to_bytes(4, byteorder='big', signed=True)", "struct.pack('>i', present_velocity)")
content = content.replace("present_position.to_bytes(4, byteorder='big', signed=True)", "struct.pack('>i', present_position)")
content = content.replace(
    "payload = bytes([status, moving, moving_status]) + current_bytes + temp_bytes + vel_bytes + pos_bytes",
    "payload = struct.pack('>BBB', status, moving, moving_status) + current_bytes + temp_bytes + vel_bytes + pos_bytes"
)

with open('/home/user/Shelfa/ros2_ws/src/Doosan-E0509-ROBOTIS-RH-P12-RN-TCP-Bridge/dsr_gripper_tcp/dsr_gripper_tcp/gripper_tcp_bridge.py', 'w') as f:
    f.write(content)
