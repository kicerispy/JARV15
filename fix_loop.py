with open('agent_loop.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Keep everything up to where the main block usually starts
valid_lines = []
for line in lines:
    if 'if __name__' in line:
        break
    valid_lines.append(line)

# Add the correct main block with explicit, standard 4-space indentation
valid_lines.append('\nif __name__ == "__main__":\n')
valid_lines.append('    import sys\n')
valid_lines.append('    task_prompt = sys.argv[1] if len(sys.argv) > 1 else "Play the wifiskeleton video on YouTube"\n')
valid_lines.append('    run_agent(task_prompt)\n')
valid_lines.append('    print("\\n[JARVIS] Task complete! Browser is running. Press ENTER in this console to close...")\n')
valid_lines.append('    try:\n')
valid_lines.append('        input()\n')
valid_lines.append('    except KeyboardInterrupt:\n')
valid_lines.append('        pass\n')

with open('agent_loop.py', 'w', encoding='utf-8') as f:
    f.writelines(valid_lines)

print("agent_loop.py indentation completely cleaned and fixed!")
