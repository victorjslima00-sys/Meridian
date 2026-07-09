import re

with open('src/App.jsx', 'r') as f:
    content = f.read()

content = content.replace("new WebSocket", "new window.WebSocket")
content = content.replace("confirm(", "window.confirm(")
content = content.replace("} catch (e) {}", "} catch (e) { console.error('Audio error', e); }")

with open('src/App.jsx', 'w') as f:
    f.write(content)
