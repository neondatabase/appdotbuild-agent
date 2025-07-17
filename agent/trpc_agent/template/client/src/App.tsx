import './App.css';

function App() {
  return (
    <div>
      <div className="gradient"></div>
      <div className="grid"></div>
      <div className="container">
        <h1 className="title">Under Construction</h1>
        <p className="description">
          Your app is under construction. It's being built right now!
        </p>
        <div className="dots">
          <div className="dot"></div>
          <div className="dot"></div>
          <div className="dot"></div>
        </div>
        <footer className="footer">
          Built with ❤️ by{" "}
          <a href="https://app.build" target="_blank" className="footer-link">
            app.build
          </a>
        </footer>
      </div>
    </div>
  );
}

export default App;
