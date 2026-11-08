// Pure Vanilla JS Numismatic Loupe for blueyco.in
function initCoinLoupe(containerSelector, zoomRatio = 2.5) {
  const container = document.querySelector(containerSelector);
  if (!container) return;
  const smallImg = container.querySelector('img.loupe-target');
  if (!smallImg) return;

  let lens = container.querySelector('.loupe-lens');
  if (!lens) {
    lens = document.createElement('div');
    lens.className = 'loupe-lens';
    Object.assign(lens.style, {
      position: 'absolute',
      width: '180px',
      height: '180px',
      borderRadius: '50%',
      border: '3px solid rgba(255,255,255,0.9)',
      boxShadow: '0 4px 20px rgba(0,0,0,0.4), inset 0 0 10px rgba(0,0,0,0.25)',
      pointerEvents: 'none',
      display: 'none',
      backgroundRepeat: 'no-repeat',
      zIndex: '100'
    });
    container.style.position = 'relative';
    container.style.overflow = 'hidden';
    container.appendChild(lens);
  }

  function updateLens(e) {
    const rect = smallImg.getBoundingClientRect();
    const clientX = e.clientX || (e.touches && e.touches[0].clientX);
    const clientY = e.clientY || (e.touches && e.touches[0].clientY);
    if (!clientX || !clientY) return;

    const x = clientX - rect.left;
    const y = clientY - rect.top;

    if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
      lens.style.display = 'none';
      return;
    }

    lens.style.display = 'block';
    lens.style.left = `${x - lens.offsetWidth / 2}px`;
    lens.style.top = `${y - lens.offsetHeight / 2}px`;

    const highRes = smallImg.dataset.highres || smallImg.src;
    lens.style.backgroundImage = `url("${highRes}")`;
    lens.style.backgroundSize = `${rect.width * zoomRatio}px ${rect.height * zoomRatio}px`;
    lens.style.backgroundPosition = `-${x * zoomRatio - lens.offsetWidth / 2}px -${y * zoomRatio - lens.offsetHeight / 2}px`;
  }

  container.addEventListener('mousemove', updateLens);
  container.addEventListener('mouseleave', () => { lens.style.display = 'none'; });
  container.addEventListener('touchmove', updateLens, { passive: true });
  container.addEventListener('touchend', () => { lens.style.display = 'none'; });
}

if (typeof module !== 'undefined') {
  module.exports = { initCoinLoupe };
}
