const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());

// Public transcript endpoints
app.get('/api/transcripts', (req, res) => {
  res.json({ 
     transcripts: [],
     message: "Transcript endpoint - Mercury program"
  });
});

app.post('/api/transcripts', (req, res) => {
  const { topic, content, contributorId } = req.body;
  
  if (!topic || !content || !contributorId) {
    return res.status(400).json({ error: 'Missing required fields' });
  }
  
  // Validate no sensitive data
  if (containsSensitiveData(content)) {
    return res.status(400).json({ error: 'Content contains sensitive data' });
  }
  
  res.json({ 
    success: true,
    message: 'Transcript submitted successfully'
  });
});

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'peer-link' });
});

app.listen(PORT, () => {
  console.log(`Peer Link server running on port ${PORT}`);
});

function containsSensitiveData(text) {
  const sensitivePatterns = [
    /banking.?credential/i,
    /account.?identifier/i,
    /routing.?number/i,
    /\b\d{3}-\d{2}-\d{4}\b/, // SSN-like pattern
    /\b\d{10,}\b/ // Long numeric sequences
  ];
  
  return sensitivePatterns.some(pattern => pattern.test(text));
}

module.exports = app;
