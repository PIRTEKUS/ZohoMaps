path = r'C:\Users\frapa\GitHub Projects\ZohoMap\templates\settings.html'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == 'style="grid-column: 1 / -1; border-color: rgba(99,102,241,0.35);">':
        lines[i] = '        <div class="settings-card glass" id="service-token-card" style="grid-column: 1 / -1; border-color: rgba(99,102,241,0.35);">\n'
        print(f"Fixed line {i+1}")
        break

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("Done")
