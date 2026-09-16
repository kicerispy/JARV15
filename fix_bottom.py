with open('agent_loop.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Cut off anything after run_agent definition or old main blocks
if 'if __name__' in content:
    content = content.split('if __name__')[0]
elif 'run_agent' in content:
    parts = content.split('run_agent')
    # Keep up to the end of run_agent function definition
    content = parts[0] + 'run_agent' + parts[1].split('\n\n')[0]

# Append a pristine, correctly indented execution block
pristine_block = '''

if __name__ == "__main__":
    import sys
    task_prompt = sys.argv[1] if len(sys.argv) > 1 else "Play the wifiskeleton video on YouTube"
    run_agent(task_prompt)
    print("\\n[JARVIS] Task complete! Browser is running. Press ENTER in this console to close...")
    try:
        input()
    except KeyboardInterrupt:
        pass
'''

with open('agent_loop.py', 'w', encoding='utf-8') as f:
    f.write(content.strip() + pristine_block)

print("agent_loop.py bottom block rewritten cleanly!")
