import planner

prompt = planner._planner_prompt()

print("PROMPT LENGTH:", len(prompt))
print("BAREHANDS_PRESENT COUNT:", prompt.lower().count("barehands_present"))
print("JARVIS_STATUS COUNT:", prompt.lower().count("jarvis_status"))
print()
print("=== BAREHANDS SECTION ===")
start = prompt.lower().find("barehands tool selection")
print(prompt[start:start + 1000])
