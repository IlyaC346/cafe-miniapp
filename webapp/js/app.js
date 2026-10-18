/* ===== Telegram ===== */
const tg = window.Telegram?.WebApp;
// initData пустой, если страница открыта просто в браузере
const IN_TG = Boolean(tg?.initData);

if (IN_TG) {
  tg.ready();
  tg.expand();
  document.documentElement.classList.add('tg');
  document.body.classList.add('tg-app');
  tg.setHeaderColor?.('bg_color');
}

const haptic = type => IN_TG && tg.HapticFeedback?.impactOccurred(type);

/* ===== Помощники ===== */
const $ = sel => document.querySelector(sel);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = n => new Intl.NumberFormat('ru-RU').format(n) + ' ₽';
const plural = (n, [one, few, many]) => {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
};

const storage = {
  get(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* приватный режим */ }
  },
};

let toastTimer;
function toast(text) {
  const el = $('#toast');
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 1600);
}

/* ===== Состояние ===== */
let MENU = null;
let ITEMS = {};
const cart = new Map(Object.entries(storage.get('cart', {})));  // id → количество
let screen = 'menu';

function saveCart() {
  storage.set('cart', Object.fromEntries(cart));
}

function cartCount() {
  let n = 0;
  cart.forEach(q => { n += q; });
  return n;
}

function subtotal() {
  let sum = 0;
  cart.forEach((q, id) => { sum += (ITEMS[id]?.price || 0) * q; });
  return sum;
}

function orderType() {
  return $('#checkout-form').elements.type.value;
}

function deliveryFee() {
  const c = MENU.cafe;
  return orderType() === 'delivery' && subtotal() < c.free_delivery_from ? c.delivery_fee : 0;
}

function setQty(id, qty) {
  if (qty <= 0) cart.delete(id);
  else cart.set(id, Math.min(qty, 20));
  saveCart();
  renderItemControls(id);
  if (screen === 'checkout') renderCheckout();
  updateMainButton();
}

/* ===== Меню ===== */
function controlsHtml(id) {
  const q = cart.get(id) || 0;
  return q
    ? `<div class="counter"><button data-dec="${id}" aria-label="Убрать одну">−</button><span>${q}</span><button data-inc="${id}" aria-label="Добавить ещё">+</button></div>`
    : `<button class="add-btn" data-inc="${id}">${money(ITEMS[id].price)}</button>`;
}

function renderItemControls(id) {
  const box = document.querySelector(`[data-controls="${id}"]`);
  if (box) box.innerHTML = controlsHtml(id);
}

function renderMenu() {
  const c = MENU.cafe;
  $('#cafe-name').textContent = c.name;
  $('#cafe-info').textContent = `${c.tagline} · ${c.hours}`;
  $('#promo').innerHTML = `<div class="promo__inner">🛵 Бесплатная доставка от ${money(c.free_delivery_from)} · самовывоз: ${esc(c.address)}</div>`;

  $('#cats').innerHTML = MENU.categories
    .map((cat, i) => `<button class="cat${i ? '' : ' is-active'}" data-cat="${cat.id}">${esc(cat.title)}</button>`)
    .join('');

  $('#menu').innerHTML = MENU.categories.map(cat => `
    <h2 class="menu__title" id="cat-${cat.id}">${esc(cat.title)}</h2>
    <div class="grid">
      ${MENU.items.filter(it => it.category === cat.id).map(it => `
        <article class="item">
          ${it.tags[0] ? `<span class="item__tag item__tag--${esc(it.tags[0])}">${esc(it.tags[0])}</span>` : ''}
          <div class="item__pic" aria-hidden="true">${it.emoji}</div>
          <div class="item__name">${esc(it.name)}</div>
          <div class="item__desc">${esc(it.desc)}</div>
          <div class="item__weight">${esc(it.weight)}</div>
          <div class="item__foot" data-controls="${it.id}">${controlsHtml(it.id)}</div>
        </article>`).join('')}
    </div>`).join('');
}

// Кнопки + и − (делегирование и для меню, и для корзины)
document.addEventListener('click', e => {
  const inc = e.target.closest('[data-inc]');
  const dec = e.target.closest('[data-dec]');
  if (inc) {
    const id = inc.dataset.inc;
    if ((cart.get(id) || 0) === 0) toast(`${ITEMS[id].name} — в корзине`);
    setQty(id, (cart.get(id) || 0) + 1);
    haptic('light');
  } else if (dec) {
    setQty(dec.dataset.dec, (cart.get(dec.dataset.dec) || 0) - 1);
    haptic('light');
  }
});

// Категории: клик — прокрутка, прокрутка — подсветка
$('#cats').addEventListener('click', e => {
  const btn = e.target.closest('[data-cat]');
  if (btn) document.getElementById(`cat-${btn.dataset.cat}`).scrollIntoView({ behavior: 'smooth' });
});

function highlightCategory() {
  if (screen !== 'menu' || !MENU) return;
  let current = MENU.categories[0].id;
  for (const cat of MENU.categories) {
    if (document.getElementById(`cat-${cat.id}`).getBoundingClientRect().top < 120) current = cat.id;
  }
  document.querySelectorAll('.cat').forEach(b => {
    const active = b.dataset.cat === current;
    if (active && !b.classList.contains('is-active')) b.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
    b.classList.toggle('is-active', active);
  });
}
window.addEventListener('scroll', highlightCategory, { passive: true });

/* ===== Оформление ===== */
function timeOptions(now = new Date()) {
  const opts = [];
  const close = new Date(now); close.setHours(22, 30, 0, 0);
  const open = new Date(now); open.setHours(11, 30, 0, 0);
  const pad = n => String(n).padStart(2, '0');
  const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  let t = new Date(now.getTime() + 60 * 60 * 1000);
  t.setMinutes(t.getMinutes() < 30 ? 30 : 60, 0, 0);
  if (t < open) t = open;

  if (now >= open && now <= new Date(close.getTime() - 45 * 60 * 1000)) {
    opts.push(['asap', 'Как можно скорее']);
  }
  let prefix = '';
  if (t > close) {  // сегодня уже поздно — предлагаем завтра
    t = new Date(open.getTime() + 24 * 3600 * 1000);
    close.setDate(close.getDate() + 1);
    prefix = 'Завтра, ';
  }
  for (; t <= close && opts.length < 24; t = new Date(t.getTime() + 30 * 60 * 1000)) {
    opts.push([iso(t), `${prefix}${pad(t.getHours())}:${pad(t.getMinutes())}`]);
  }
  return opts;
}

function renderCheckout() {
  const ids = [...cart.keys()].filter(id => ITEMS[id]);
  if (!ids.length) { showScreen('menu'); return; }

  $('#cart').innerHTML = ids.map(id => {
    const it = ITEMS[id], q = cart.get(id);
    return `<li>
      <div class="cart__emoji" aria-hidden="true">${it.emoji}</div>
      <div class="cart__info"><div class="cart__name">${esc(it.name)}</div><div class="cart__price">${money(it.price)} × ${q} = ${money(it.price * q)}</div></div>
      <div class="counter"><button data-dec="${id}" aria-label="Убрать одну">−</button><span>${q}</span><button data-inc="${id}" aria-label="Добавить ещё">+</button></div>
    </li>`;
  }).join('');

  const c = MENU.cafe, sub = subtotal(), fee = deliveryFee(), isDelivery = orderType() === 'delivery';
  let hint = '';
  if (isDelivery && fee) hint = `Добавьте ещё на ${money(c.free_delivery_from - sub)} — доставка будет бесплатной`;
  if (sub < c.min_order) hint = `Минимальная сумма заказа — ${money(c.min_order)}`;

  $('#totals').innerHTML = `
    <dt>Товары (${cartCount()})</dt><dd>${money(sub)}</dd>
    ${isDelivery ? `<dt>Доставка</dt><dd>${fee ? money(fee) : 'бесплатно'}</dd>` : ''}
    <dt class="total">Итого</dt><dd class="total">${money(sub + fee)}</dd>
    ${hint ? `<p class="hint">${hint}</p>` : ''}`;

  $('#address-field').hidden = !isDelivery;
  $('#pickup-note').hidden = isDelivery;
  $('#pickup-note').textContent = `📍 Заберите заказ по адресу: ${c.address}`;
}

function fillTimes() {
  $('#time-select').innerHTML = timeOptions().map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
}

$('#checkout-form').addEventListener('change', e => {
  if (e.target.name === 'type') { renderCheckout(); updateMainButton(); }
});

$('#clear-btn').addEventListener('click', () => {
  const clear = () => {
    cart.clear();
    saveCart();
    renderMenu();
    showScreen('menu');
  };
  if (IN_TG) tg.showConfirm('Очистить корзину?', ok => ok && clear());
  else if (confirm('Очистить корзину?')) clear();
});

/* ===== Телефон ===== */
const phoneInput = $('#checkout-form').elements.phone;

function formatPhone(value) {
  let d = value.replace(/\D/g, '');
  if (!d) return '';
  if (d[0] === '8') d = '7' + d.slice(1);
  if (d[0] !== '7') d = '7' + d;
  d = d.slice(1, 11);
  let r = '+7';
  if (d.length) r += ' (' + d.slice(0, 3);
  if (d.length >= 3) r += ')';
  if (d.length > 3) r += ' ' + d.slice(3, 6);
  if (d.length > 6) r += '-' + d.slice(6, 8);
  if (d.length > 8) r += '-' + d.slice(8, 10);
  return r;
}
phoneInput.addEventListener('input', () => { phoneInput.value = formatPhone(phoneInput.value); });

/* ===== Отправка ===== */
function setError(input, msg) {
  const field = input.closest('.field');
  field.classList.toggle('has-error', Boolean(msg));
  field.querySelector('.field__error').textContent = msg || '';
}

function validate() {
  const f = $('#checkout-form').elements;
  let ok = true;
  if (orderType() === 'delivery' && f.address.value.trim().length < 5) {
    setError(f.address, 'Укажите адрес доставки'); ok = false;
  } else setError(f.address, '');
  if (f.phone.value.replace(/\D/g, '').length !== 11) {
    setError(f.phone, 'Введите номер полностью'); ok = false;
  } else setError(f.phone, '');
  if (subtotal() < MENU.cafe.min_order) {
    $('#form-msg').textContent = `Минимальная сумма заказа — ${money(MENU.cafe.min_order)}`; ok = false;
  } else $('#form-msg').textContent = '';
  return ok;
}

function buildOrder() {
  const f = $('#checkout-form').elements;
  return {
    v: 1,
    items: [...cart.entries()].filter(([id]) => ITEMS[id]).map(([id, q]) => [id, q]),
    type: orderType(),
    address: orderType() === 'delivery' ? f.address.value.trim().slice(0, 200) : '',
    phone: f.phone.value,
    time: f.time.value,
    payment: f.payment.value,
    comment: f.comment.value.trim().slice(0, 300),
    total: subtotal() + deliveryFee(),  // бот всё равно пересчитает по своему меню
  };
}

function submitOrder() {
  if (!validate()) {
    haptic('heavy');
    return;
  }
  const order = buildOrder();
  storage.set('profile', { phone: order.phone, address: $('#checkout-form').elements.address.value });

  if (IN_TG) {
    cart.clear();
    saveCart();
    tg.sendData(JSON.stringify(order));  // Telegram закроет приложение и передаст данные боту
    return;
  }
  $('#sheet-json').textContent = JSON.stringify(order, null, 2);
  $('#sheet').hidden = false;
}

$('#sheet-close').addEventListener('click', () => {
  $('#sheet').hidden = true;
  cart.clear();
  saveCart();
  renderMenu();
  showScreen('menu');
});

/* ===== Экраны и главная кнопка ===== */
function showScreen(name) {
  screen = name;
  $('#screen-menu').hidden = name !== 'menu';
  $('#screen-checkout').hidden = name !== 'checkout';
  if (name === 'checkout') {
    fillTimes();
    renderCheckout();
  }
  if (IN_TG) {
    if (name === 'checkout') tg.BackButton.show(); else tg.BackButton.hide();
  }
  window.scrollTo(0, 0);
  updateMainButton();
}

function mainButtonState() {
  const count = cartCount();
  if (screen === 'menu') {
    return count
      ? { visible: true, text: `Корзина · ${count} ${plural(count, ['товар', 'товара', 'товаров'])} · ${money(subtotal())}` }
      : { visible: false };
  }
  return { visible: true, text: `Заказать · ${money(subtotal() + deliveryFee())}` };
}

function updateMainButton() {
  const s = mainButtonState();
  if (IN_TG) {
    if (s.visible) {
      tg.MainButton.setParams({ text: s.text, color: '#e2541b', text_color: '#ffffff', is_visible: true });
    } else tg.MainButton.hide();
  } else {
    $('#bottom-bar').hidden = !s.visible;
    $('#main-btn').textContent = s.text || '';
  }
}

function onMainButton() {
  if (screen === 'menu') showScreen('checkout');
  else submitOrder();
}

if (IN_TG) {
  tg.MainButton.onClick(onMainButton);
  tg.BackButton.onClick(() => showScreen('menu'));
} else {
  $('#main-btn').addEventListener('click', onMainButton);
}
$('#back-btn').addEventListener('click', () => showScreen('menu'));

/* ===== Запуск ===== */
async function init() {
  MENU = await fetch('menu.json').then(r => r.json());
  ITEMS = Object.fromEntries(MENU.items.map(it => [it.id, it]));
  [...cart.keys()].forEach(id => { if (!ITEMS[id]) cart.delete(id); });

  const profile = storage.get('profile', {});
  const f = $('#checkout-form').elements;
  f.phone.value = profile.phone || '';
  f.address.value = profile.address || '';

  renderMenu();
  updateMainButton();
}

init().catch(() => {
  $('#menu').innerHTML = '<p style="padding:24px;text-align:center">Не удалось загрузить меню. Проверьте интернет и откройте приложение снова.</p>';
});
