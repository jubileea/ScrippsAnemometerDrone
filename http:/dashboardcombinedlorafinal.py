import threading
import time
import csv
import smbus
import serial
from datetime import datetime
from flask import Flask, render_template_string, jsonify


# on rpi logging to dashboardcom1, 2, etc


# === CONFIG ===
MAX_POINTS = 50  # Number of points on each graph


# === Shared Data ===
data_lock = threading.Lock()
plot_data = {
    "timestamps": [],
    "i2c": {
        "humidity": [],
        "temperature": [],
        "pressure": [],
        "altitude": []
    },
    "anem": {
        "humidity": [],
        "temperature": [],
        "pressure": [],
        "windspeed": []
    }
}


# === Sensor Reading Functions ===
def read_i2c_sensors():
    bus = smbus.SMBus(1)
    data = {}
    try:
        # HYT939 Humidity/Temp
        bus.write_byte(0x28, 0x80)
        time.sleep(0.1)
        hyt_data = bus.read_i2c_block_data(0x28, 0x00, 4)
        data['HYT939_RH_%'] = round(((hyt_data[0] & 0x3F) * 256 + hyt_data[1]) * (100 / 16383.0), 2)
        data['HYT939_temp_C'] = round(((hyt_data[2] * 256 + (hyt_data[3] & 0xFC)) / 4) * (165 / 16383.0) - 40, 2)


        # HP206C Pressure/Alt/Temp
        bus.write_byte(0x76, 0x44 | 0x00)
        time.sleep(0.1)
        hp_data = bus.read_i2c_block_data(0x76, 0x10, 6)
        data['HP206C_pressure_mbar'] = round((((hp_data[3] & 0x0F) * 65536) + (hp_data[4] * 256) + hp_data[5]) / 100.0, 2)
        data['HP206C_temp_C'] = round((((hp_data[0] & 0x0F) * 65536) + (hp_data[1] * 256) + hp_data[2]) / 100.0, 2)


        # HP206C Altitude
        bus.write_byte(0x76, 0x44 | 0x01)
        time.sleep(0.1)
        alt_data = bus.read_i2c_block_data(0x76, 0x31, 3)
        data['HP206C_altitude_m'] = round((((alt_data[0] & 0x0F) * 65536) + (alt_data[1] * 256) + alt_data[2]) / 100.0, 2)
    except Exception as e:
        data['HYT939_RH_%'] = None
        data['HYT939_temp_C'] = None
        data['HP206C_pressure_mbar'] = None
        data['HP206C_temp_C'] = None
        data['HP206C_altitude_m'] = None
    finally:
        bus.close()
    return data


def parse_anemometer(anem_str):
    """
    Parses anemometer string like:
    S 00.06 D 187 U 00.01 V 00.06 W 00.00 T 22.05 H 50.23 P 1009.01 ...
    Returns dict with temperature, humidity, pressure, windspeed.
    """
    result = {"temperature": None, "humidity": None, "pressure": None, "windspeed": None}
    if not anem_str:
        return result
    try:
        tokens = anem_str.split()
        i = 0
        while i < len(tokens) - 1:
            label = tokens[i]
            value = tokens[i+1]
            if label == 'T':
                result['temperature'] = float(value)
            elif label == 'H':
                result['humidity'] = float(value)
            elif label == 'P':
                result['pressure'] = float(value)
            elif label == 'S':
                result['windspeed'] = float(value)
            i += 2
    except Exception as e:
        print(f"Error parsing anemometer string: {e}")
    return result


# === Data Collection and Logging Thread ===
def data_collector(csv_filename):
    
    ser1 = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
    ser2 = serial.Serial('/dev/ttyUSB1',115200,timeout=1)
    with open(csv_filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            'timestamp',
            'i2c_humidity', 'i2c_temperature', 'i2c_pressure', 'i2c_altitude',
            'anem_humidity', 'anem_temperature', 'anem_pressure', 'anem_windspeed'
        ])
        try:
            while True:
                i2c = read_i2c_sensors()
                # Read until a non-empty anemometer line is found (max 10 tries)
                anem_line = ""
                for _ in range(10):
                    anem_line = ser1.readline().decode(errors='ignore').strip()
                    if anem_line:
                        break
                anem = parse_anemometer(anem_line)
                timestamp = datetime.now().strftime('%H:%M:%S')


                with data_lock:
                    # Keep lists at MAX_POINTS length
                    if len(plot_data["timestamps"]) >= MAX_POINTS:
                        plot_data["timestamps"].pop(0)
                        for k in plot_data["i2c"]:
                            plot_data["i2c"][k].pop(0)
                        for k in plot_data["anem"]:
                            plot_data["anem"][k].pop(0)
                    # Append new data
                    plot_data["timestamps"].append(timestamp)
                    plot_data["i2c"]["humidity"].append(i2c['HYT939_RH_%'])
                    plot_data["i2c"]["temperature"].append(i2c['HYT939_temp_C'])
                    plot_data["i2c"]["pressure"].append(i2c['HP206C_pressure_mbar'])
                    plot_data["i2c"]["altitude"].append(i2c['HP206C_altitude_m'])
                    plot_data["anem"]["humidity"].append(anem["humidity"])
                    plot_data["anem"]["temperature"].append(anem["temperature"])
                    plot_data["anem"]["pressure"].append(anem["pressure"])
                    plot_data["anem"]["windspeed"].append(anem["windspeed"])


                # Prepare row for CSV and terminal display
                row = [
                    timestamp,
                    i2c['HYT939_RH_%'], i2c['HYT939_temp_C'], i2c['HP206C_pressure_mbar'], i2c['HP206C_altitude_m'],
                    anem["humidity"], anem["temperature"], anem["pressure"], anem["windspeed"]
                ]


                # Print to terminal in a readable format
                print(
                    f"{timestamp} | "
                    f"I2C: Humidity {i2c['HYT939_RH_%']}% | Temp {i2c['HYT939_temp_C']}°C | "
                    f"Pressure {i2c['HP206C_pressure_mbar']} mbar | Altitude {i2c['HP206C_altitude_m']} m || "
                    f"Anem: Humidity {anem['humidity']}% | Temp {anem['temperature']}°C | "
                    f"Pressure {anem['pressure']} mbar | Wind {anem['windspeed']} m/s"
                )
                combined_data = f"{i2c['HYT939_RH_%']}, {i2c['HYT939_temp_C']}, {i2c['HP206C_pressure_mbar']}, {i2c['HP206C_altitude_m']}, {anem['humidity']}, {anem['temperature']}, {anem['pressure']}, {anem['windspeed']}"
                    
                ser2.write((combined_data + "\n").encode('utf-8')) #This should be working, I am just trying to write my string of data to serial to read it in the arduino
                ser2.flush()
                # Log to CSV
                writer.writerow(row)
                csvfile.flush()
                time.sleep(.1)  # Adjust as needed
        except KeyboardInterrupt:
            print("\nLogging stopped by user. CSV file closed.")
        finally:
            ser1.close()
            ser2.close()


# === Flask Dashboard ===
app = Flask(__name__)


HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Live Sensor Dashboard</title>
    <meta charset="utf-8">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
    .chart-container {
        width: 98vw;
        max-width: 700px;
        margin: 0 auto 20px auto;
        display: block;
    }
    body {
        margin: 0;
        padding: 0;
        font-family: sans-serif;
        background: #fafafa;
    }
    h1, h3 {
        text-align: center;
    }
    canvas {
        width: 100% !important;
        height: 250px !important;
        max-width: 100vw !important;
    }
    </style>
</head>
<body>
    <h1>Live Sensor Dashboard</h1>
    <div class="chart-container">
        <h3>Humidity (%)</h3>
        <canvas id="humidityChart"></canvas>
    </div>
    <div class="chart-container">
        <h3>Pressure (mbar)</h3>
        <canvas id="pressureChart"></canvas>
    </div>
    <div class="chart-container">
        <h3>Temperature (°C)</h3>
        <canvas id="temperatureChart"></canvas>
    </div>
    <div class="chart-container">
        <h3>Altitude (m) & Wind Speed (m/s)</h3>
        <canvas id="altwindChart"></canvas>
    </div>
<script>
function makeChart(ctx, label1, color1, label2, color2, yLabel) {
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                { label: label1, borderColor: color1, backgroundColor: color1+'33', data: [], spanGaps: true },
                { label: label2, borderColor: color2, backgroundColor: color2+'33', data: [], spanGaps: true }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: { y: { title: { display: true, text: yLabel } } }
        }
    });
}
var humidityChart = makeChart(document.getElementById('humidityChart').getContext('2d'),
    'I2C Humidity', 'rgba(54,162,235,1)', 'Anemometer Humidity', 'rgba(255,99,132,1)', 'Humidity (%)');
var pressureChart = makeChart(document.getElementById('pressureChart').getContext('2d'),
    'I2C Pressure', 'rgba(54,162,235,1)', 'Anemometer Pressure', 'rgba(255,99,132,1)', 'Pressure (mbar)');
var temperatureChart = makeChart(document.getElementById('temperatureChart').getContext('2d'),
    'I2C Temp', 'rgba(54,162,235,1)', 'Anemometer Temp', 'rgba(255,99,132,1)', 'Temperature (°C)');
var altwindChart = makeChart(document.getElementById('altwindChart').getContext('2d'),
    'I2C Altitude', 'rgba(54,162,235,1)', 'Anemometer Wind Speed', 'rgba(255,99,132,1)', 'Altitude/Wind Speed');


function fetchData() {
    fetch('/plot_data').then(r => r.json()).then(data => {
        humidityChart.data.labels = data.timestamps;
        humidityChart.data.datasets[0].data = data.i2c.humidity;
        humidityChart.data.datasets[1].data = data.anem.humidity;
        humidityChart.update();


        pressureChart.data.labels = data.timestamps;
        pressureChart.data.datasets[0].data = data.i2c.pressure;
        pressureChart.data.datasets[1].data = data.anem.pressure;
        pressureChart.update();


        temperatureChart.data.labels = data.timestamps;
        temperatureChart.data.datasets[0].data = data.i2c.temperature;
        temperatureChart.data.datasets[1].data = data.anem.temperature;
        temperatureChart.update();


        altwindChart.data.labels = data.timestamps;
        altwindChart.data.datasets[0].data = data.i2c.altitude;
        altwindChart.data.datasets[1].data = data.anem.windspeed;
        altwindChart.update();
    });
}
setInterval(fetchData, 2000);
window.onload = fetchData;
</script>
</body>
</html>
"""




@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/plot_data')
def plot_data_api():
    with data_lock:
        return jsonify(plot_data)


# === Main ===
if __name__ == '__main__':
    # Prompt for CSV filename
    
 filename = datetime.now().strftime("sensorlog_%Y%m%d_%H%M%S")
csv_filename = filename + ".csv"
print(f"Logging to {csv_filename}")


    # Start data collection/logging thread
collector_thread = threading.Thread(target=data_collector, args=(csv_filename,), daemon=True)
collector_thread.start()


    # Start Flask web server (main thread, blocks)
try:
    app.run(host='0.0.0.0', port=5000, debug=False)
except KeyboardInterrupt:
    print("\nDashboard stopped by user.")
