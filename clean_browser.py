with open('browser_controller.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace non-breaking spaces with standard spaces
cleaned_content = content.replace('\xa0', ' ')

with open('browser_controller.py', 'w', encoding='utf-8') as f:
    f.write(cleaned_content)

print('Non-breaking spaces removed from browser_controller.py!')
