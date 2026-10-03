/**
 * A static stand-in for a generated application, rendered through srcDoc so
 * preview specimens show realistic content without a running sandbox.
 */
export const GENERATED_APP_MOCK = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root { color-scheme: light; font-family: ui-sans-serif, system-ui, sans-serif; }
  body { margin: 0; background: #faf8f5; color: #2b2522; }
  header { display: flex; justify-content: space-between; align-items: center; padding: 18px 28px; border-bottom: 1px solid #ebe5de; }
  header strong { font-size: 15px; letter-spacing: -0.01em; }
  nav { display: flex; gap: 18px; font-size: 13px; color: #7a6f66; }
  main { max-width: 720px; margin: 0 auto; padding: 40px 28px; }
  h1 { font-size: 26px; letter-spacing: -0.02em; margin: 0 0 6px; }
  p { color: #7a6f66; margin: 0 0 28px; font-size: 14px; }
  .plan { display: flex; justify-content: space-between; align-items: center; padding: 16px 18px; border: 1px solid #ebe5de; border-radius: 10px; background: #fff; margin-bottom: 10px; font-size: 14px; }
  .plan span { color: #7a6f66; font-size: 13px; }
  button { font: inherit; font-size: 13px; padding: 7px 12px; border-radius: 8px; border: 1px solid #2b2522; background: #2b2522; color: #faf8f5; }
  .weeks { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 28px; }
  .week { padding: 12px; border-radius: 8px; background: #fff; border: 1px solid #ebe5de; font-size: 12px; color: #7a6f66; }
  .week b { display: block; color: #2b2522; font-size: 13px; margin-bottom: 2px; }
  .paused { opacity: .45; }
</style>
</head>
<body>
  <header><strong>Roastery</strong><nav><span>Plans</span><span>Deliveries</span><span>Account</span></nav></header>
  <main>
    <h1>Your subscription</h1>
    <p>Two bags every other Monday. Next roast ships October 12.</p>
    <div class="plan"><div>House Espresso · 2 × 340 g<br /><span>Every 2 weeks</span></div><button>Change plan</button></div>
    <div class="weeks">
      <div class="week paused"><b>Oct 5</b>Paused</div>
      <div class="week"><b>Oct 12</b>Scheduled</div>
      <div class="week"><b>Oct 26</b>Scheduled</div>
      <div class="week"><b>Nov 9</b>Scheduled</div>
    </div>
  </main>
</body>
</html>`;
