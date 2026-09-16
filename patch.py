with open('agent_loop.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Filter out old main blocks if any exist at the end
clean_lines = [line for line in lines if 'if __name__ == "__main__":' not in line and 'run_agent' not in line]

# Append the correct clean block
clean_lines.append('\nif __name__ == "__main__":\n')
clean_lines.append('    import sys\n')
clean_lines.append('    task_prompt = sys.argv[1] if len(sys.argv) > 1 else "Play the wifiskeleton video on YouTube"\n')
clean_lines.append('    run_agent(task_prompt)\n')
clean_lines.append('    print("\\n[JARVIS] Task complete! Browser is running. Press ENTER in this console to close...")\n')
clean_lines.append('    try:\n')
clean_lines.append('        input()\n')
clean_lines.append('    except KeyboardInterrupt:\n')
clean_lines.append('        pass\n')

with open('agent_loop.py', 'w', encoding='utf-8') as f:
    f.writelines(clean_lines)

print("agent_loop.py successfully patched!")
