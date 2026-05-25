document.addEventListener('DOMContentLoaded', () => {

  /* ─────────────────────────────────────────────────────────
     1. Dynamic Canvas Background
     ───────────────────────────────────────────────────────── */
  const canvas = document.getElementById('bg-canvas');
  if (canvas) {
    const ctx = canvas.getContext('2d');
    let width, height;
    const particles = [];
    
    function resize() {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    }
    window.addEventListener('resize', resize);
    resize();
    
    // Create subtle particles
    const numParticles = 40;
    for (let i = 0; i < numParticles; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        size: Math.random() * 2 + 0.5
      });
    }
    
    function draw() {
      ctx.clearRect(0, 0, width, height);
      
      // Draw fireflies
      particles.forEach((p) => {
        p.x += p.vx;
        p.y += p.vy;
        
        // Bounce off edges softly
        if (p.x < 0 || p.x > width) p.vx *= -1;
        if (p.y < 0 || p.y > height) p.vy *= -1;
        
        // Pulse opacity (firefly effect)
        // using sine wave based on time and index for unique pulsing
        const time = Date.now() / 1000;
        const pulse = Math.abs(Math.sin(time * 2 + p.x));
        const opacity = 0.2 + (pulse * 0.6); // 0.2 to 0.8 for a brighter glow
        
        // Warm golden/yellow fireflies
        ctx.fillStyle = `rgba(255, 230, 100, ${opacity})`;
        
        // Draw the soft glowing orb
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * 1.5, 0, Math.PI * 2);
        ctx.fill();
      });
      
      requestAnimationFrame(draw);
    }
    draw();
  }

  /* ─────────────────────────────────────────────────────────
     2. Scroll Reveal Animations
     ───────────────────────────────────────────────────────── */
  const revealElements = document.querySelectorAll('.reveal-on-scroll');
  if (revealElements.length > 0) {
    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: "0px 0px -50px 0px" });
    
    revealElements.forEach(el => revealObserver.observe(el));
    
    // Fallback: observe DOM mutations for dynamically loaded htmx content
    document.body.addEventListener('htmx:afterSwap', function(evt) {
      const newReveals = evt.detail.elt.querySelectorAll('.reveal-on-scroll');
      newReveals.forEach(el => revealObserver.observe(el));
    });
  }



  /* ─────────────────────────────────────────────────────────
     4. Custom Glass Cursor
     ───────────────────────────────────────────────────────── */
  const cursor = document.getElementById('custom-cursor');
  if (cursor) {
    let mouseX = window.innerWidth / 2;
    let mouseY = window.innerHeight / 2;
    let cursorX = mouseX;
    let cursorY = mouseY;
    
    document.addEventListener('mousemove', (e) => {
      // On the very first move, snap the coordinates instantly and fade it in
      if (!cursor.classList.contains('active')) {
        cursorX = e.clientX;
        cursorY = e.clientY;
        cursor.classList.add('active');
      }
      mouseX = e.clientX;
      mouseY = e.clientY;
    });
    
    // Smooth follow loop
    function renderCursor() {
      // Lerp (Linear Interpolation) for a laggy, fluid premium feel
      cursorX += (mouseX - cursorX) * 0.25;
      cursorY += (mouseY - cursorY) * 0.25;
      
      // For a pointy arrow, the hot-spot is at the top-left (0,0), so no offset needed.
      cursor.style.transform = `translate(${cursorX}px, ${cursorY}px)`;
      requestAnimationFrame(renderCursor);
    }
    requestAnimationFrame(renderCursor);
    
    // Add hover states to interactive elements
    const interactives = document.querySelectorAll('a, button, input, .magnetic-wrap, .row-summary, .context-menu-item');
    interactives.forEach(el => {
      el.addEventListener('mouseenter', () => cursor.classList.add('hovering'));
      el.addEventListener('mouseleave', () => cursor.classList.remove('hovering'));
    });
  }



  /* ─────────────────────────────────────────────────────────
     5. 3D Card Tilt Effect
     ───────────────────────────────────────────────────────── */
  function bindTilt(card) {
    if (card.dataset.tiltBound) return;
    card.dataset.tiltBound = 'true';
    
    // Smooth out the transform transition so it doesn't snap
    card.style.transition = 'transform 0.1s ease-out, box-shadow 0.3s ease, background 0.3s ease, border-color 0.3s ease';
    
    card.addEventListener('mousemove', (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      
      const xPct = (x / rect.width - 0.5) * 2;
      const yPct = (y / rect.height - 0.5) * 2;
      
      const tiltX = -yPct * 8; // Max 8deg
      const tiltY = xPct * 8;
      
      card.style.transform = `perspective(1000px) translateY(-4px) scale(1.02) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
    });
    
    card.addEventListener('mouseleave', () => {
      // Restore default CSS transition for mouse leave
      card.style.transition = 'all 0.3s ease';
      card.style.transform = '';
    });
  }

  function initTilt() {
    document.querySelectorAll('.stat-card').forEach(bindTilt);
  }
  
  initTilt();
  document.body.addEventListener('htmx:afterSwap', initTilt);

});
