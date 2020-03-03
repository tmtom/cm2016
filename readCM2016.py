#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import struct
import serial

from influxdb import InfluxDBClient
from datetime import datetime

SERIAL = "/dev/ttyUSB0"
 
# Open serial device for reading, it is 19200 baud, 8N1
ser = serial.Serial(SERIAL, 19200)

# supported chemicals, the 9V blocks (Slot A and B) are always NiMH!
CHEM = {
    0: 'NiMH',
    1: 'NiZn'
}

# status of the slot
ACTIVE = {
    0: 'Empty',
    1: 'Active',
}

# Selected program
PROGRAM = {
    0: "Idle",
    1: "Charge",
    2: "Discharge",
    3: "Check",
    4: "Cycle",
    5: "Alive",
    6: "No Param",
    7: "Trickle",
    8: "Waiting",
    9: "Error",
    10: "Ready",
}

# actual mode
MODES = {
    0: "---",
    1: "Charge",
    2: "Discharge",
    3: "Ready",
    4: "Ready",
    5: "Waiting",
    6: "Error",
}

# convert minutes into an hour:minutes string
def timeStr(minutes):
    return '%2.2d:%-2.2d' % (minutes / 60, minutes % 60)

# the 9V slots are named A and B, while the 1.5V slots are 1..4
def slotStr(slot):
    if slot==5:
        return 'A'
    elif slot==6:
        return 'B'
    else:
        return str(slot)


client = InfluxDBClient(database='cm2016')
while True:
    # make sure that are no old bytes left in the input buffer
    ser.reset_input_buffer()

    # FYI: the devices sends one package per second

    # each packet starts with 7 bytes, which are the name of the device
    header = ser.read(7)
    if header != 'CM2016 ': # Charge Master 2016 detected?
        continue

    # the next 10 bytes are global data for all slots or the device
    header = ser.read(10)
    print('VERSION=%d.%d CHEM=%s OVERTEMP_FLAG=%d TEMP_START=%d TEMP_ACT=%d ACTION_CNTR=%d' % ( ord(header[0]),ord(header[1]),CHEM[ord(header[2])],ord(header[3]),struct.unpack(">h", header[4:6])[0],struct.unpack(">h", header[6:8])[0],struct.unpack(">h", header[8:10])[0]))

    timestamp = datetime.utcnow().isoformat()

    # the CM2016 has 6 slots, each is 18 bytes of data
    json_data = []
    for slot in range(1,7):
        slotData = ser.read(18)

        active = ord(slotData[0]) == 1
        program = PROGRAM[ord(slotData[1])]
        mode = MODES[ord(slotData[2])]
        status = "unknown"
        status_byte = ord(slotData[3])
        if status_byte == 0x20:
            status = "empty"
        if active:
            if status_byte == 0x07:
                status = "TRI"
        else:
            if status_byte == 0x21:
                status = "ERR"
            elif status_byte == 0x07 or status_byte==0x02:
                status = "RDY"

        duration = timeStr(struct.unpack("<h", slotData[4:6])[0])
        voltage = struct.unpack("<h", slotData[6:8])[0] / 1000.0
        current = struct.unpack("<h", slotData[8:10])[0] / 1000.0
        ccap = struct.unpack("<i", slotData[10:14])[0] / 100.0
        dcap = struct.unpack("<i", slotData[14:18])[0] / 100.0

        # print(active, program, mode, status)
        print('Slot S%s : %s/%s/%s/%s Time=%s Voltage=%.3fV Current=%.3fA CCAP=%.3fmAh DCAP=%.3fmAh' % (slotStr(slot),
                                                                                                          ACTIVE[ord(slotData[0])],
                                                                                                          program,
                                                                                                          mode,
                                                                                                          status,
                                                                                                          duration,
                                                                                                          voltage,
                                                                                                          current,
                                                                                                          ccap,
                                                                                                          dcap))
        data = {
            "measurement": "CM2016",
            "time": timestamp,
            "tags": {
                "slot": "S" + slotStr(slot)
            },
            "fields": {
                "active": active,
                "program": program,
                "mode": mode,
                "status": status,
                "time": duration,
                "voltage": voltage,
                "current": current,
                "ccap": ccap,
                "dcap": dcap
            }
        }
        json_data.append(data)

    # as it may take longer to write the datapoints we should probably read CM2016 and in parallel bundle and send data to InfluxDB
    if not client.write_points(json_data):
        print("Influx problem")


    # and a 16 byte CRC follows
    crc = ser.read(2)
    # the way the CRC16 is calculated is unknown to me, it either is a very uncommon one or it is initialized in a different way. The Visual Basic software from Conrad doesn't check for it, it only tests the header

    # client.write_points(json_body)
    print("")
