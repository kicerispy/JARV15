import pyautogui
import time


print("Move your mouse to the CENTER of the target you want to calibrate.")
print("You have 5 seconds...")

time.sleep(5)

x, y = pyautogui.position()

print(f"Actual mouse position: ({x}, {y})")
print("Now compare that with the coordinates JARVIS reported.")