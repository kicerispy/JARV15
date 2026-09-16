with open('agent_loop.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    # If a line is supposed to be top-level (doesn't start with space/tab and isn't empty), strip leading whitespace
    stripped = line.lstrip()
    if stripped.startswith(('import ', 'from ', 'def ', 'class ', 'if __name__', 'logging.')):
        new_lines.append(stripped)
    else:
        new_lines.append(line)

with open('agent_loop.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("agent_loop.py indentation normalized!")
