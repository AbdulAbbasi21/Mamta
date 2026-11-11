// Firestore real-time listener for the LHW dashboard (Firebase JS SDK from Google's CDN).
// Used only when firebase-config.js contains a config; otherwise the app polls the backend.
window.MamtaFirebase = {
  async listenAlerts(lhwId, onChange) {
    const cfg = window.MAMTA_FIREBASE_CONFIG;
    if (!cfg) return null;
    try {
      const { initializeApp, getApps } = await import('https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js');
      const { getFirestore, collection, query, where, onSnapshot } =
        await import('https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js');
      const app = getApps()[0] || initializeApp(cfg);
      const q = query(collection(getFirestore(app), 'alerts'), where('lhwId', '==', lhwId));
      return onSnapshot(q, () => onChange(), (e) => console.warn('Firestore listener error', e));
    } catch (e) {
      console.warn('Firebase not available, polling instead', e);
      return null;
    }
  },
};
