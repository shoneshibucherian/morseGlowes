import random
import math
import time

class GPSSimulator:
    def __init__(self, base_noise_m=3, spike_chance=0.02):
        self.base_noise_m = base_noise_m
        self.spike_chance = spike_chance
        self.drift_x = 0
        self.drift_y = 0
        self.last_update = time.time()

    def meters_to_degrees(self, meters):
        return meters * 0.000009  # approx

    def add_noise(self, lat, lon):
        now = time.time()
        dt = now - self.last_update
        self.last_update = now

        # --- Slow drift (random walk) ---
        self.drift_x += random.uniform(-0.2, 0.2) * dt
        self.drift_y += random.uniform(-0.2, 0.2) * dt

        # --- Base jitter ---
        jitter_x = random.gauss(0, self.base_noise_m)
        jitter_y = random.gauss(0, self.base_noise_m)

        # --- Occasional spike ---
        spike_x = spike_y = 0
        if random.random() < self.spike_chance:
            spike_x = random.uniform(-20, 20)  # meters
            spike_y = random.uniform(-20, 20)

        # --- Total error in meters ---
        total_x = jitter_x + self.drift_x + spike_x
        total_y = jitter_y + self.drift_y + spike_y

        # Convert to degrees
        lat_offset = self.meters_to_degrees(total_y)
        lon_offset = self.meters_to_degrees(total_x) / math.cos(math.radians(lat))

        return lat + lat_offset, lon + lon_offset