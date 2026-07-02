import re

css_path = '/Users/shakeitabhishek/Documents/Projects/Lumi/src/lumi/ui/web/static/onboarding.css'
with open(css_path, 'r') as f:
    css = f.read()

# Replace variables
vars_replacement = """
:root {
  --iris-cream:     #E3E9E5;   
  --iris-paper:     rgba(255, 255, 255, 0.08);
  --iris-ink:       #F8FAFC;
  --iris-ink-soft:  rgba(255, 255, 255, 0.7);
  --iris-mute:      rgba(255, 255, 255, 0.5);
  --iris-mute-soft: rgba(255, 255, 255, 0.3);
  --iris-line:      rgba(16, 185, 129, 0.2);
  --iris-line-soft: rgba(16, 185, 129, 0.1);
  --iris-accent:    #10B981;
  --iris-accent-deep:#059669;
  --iris-accent-soft:rgba(16, 185, 129, 0.15);
  --iris-pink:      #10B981;
  --iris-purple:    #059669;
  --iris-green:     #34D399;
  --iris-soft-pink: rgba(16, 185, 129, 0.05);
  --iris-soft-blue: rgba(16, 185, 129, 0.05);

  --grad-accent:    linear-gradient(135deg, #059669 0%, #047857 100%);
  --grad-page:      url('/static/lumi-background.png');
}
"""
css = re.sub(r':root\s*\{.*?\n\}', vars_replacement.strip(), css, flags=re.DOTALL)

# Update body.onboarding
css = re.sub(r'body\.onboarding\s*\{[^}]*\}', '''body.onboarding {
  background: var(--grad-page);
  background-size: cover;
  background-position: center;
  background-attachment: fixed;
  color: var(--iris-ink);
  font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 15px;
  line-height: 1.55;
  letter-spacing: -0.005em;
  margin: 0;
  min-height: 100vh;
}''', css)

# Update fonts
css = re.sub(r'font-family:\s*\'Geist Mono\'.*?;', "font-family: 'Space Grotesk', ui-monospace, monospace;", css)
css = re.sub(r'font-family:\s*\'Crimson Pro\'.*?;', "font-family: 'Outfit', sans-serif;", css)
css = re.sub(r'font-family:\s*\'Inter\'.*?;', "font-family: 'Outfit', sans-serif;", css)

# Update ob-topbar background
css = re.sub(r'background:\s*rgba\(255,\s*255,\s*255,\s*0\.55\);', 'background: rgba(0, 0, 0, 0.4);', css)

# Update cards to be glassmorphic
css = re.sub(r'\.ob-card\s*\{\s*background:\s*var\(--iris-paper\);', """.ob-card {
  background: var(--iris-paper);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid var(--iris-line);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);""", css)

with open(css_path, 'w') as f:
    f.write(css)

base_path = '/Users/shakeitabhishek/Documents/Projects/Lumi/src/lumi/ui/web/templates/onboarding/_base.html'
with open(base_path, 'r') as f:
    html = f.read()

# Replace fonts in _base.html
html = re.sub(r'<link href="https://fonts\.googleapis\.com/css2.*?rel="stylesheet">', 
              '<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">', html)

with open(base_path, 'w') as f:
    f.write(html)

print('Onboarding CSS and HTML updated.')
