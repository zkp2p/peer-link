const express = require('express');
const { validateTranscriptSchema, createTranscript } = require('./schema');

const app = express();
const PORT = process.env.PORT || 3000;

// In-memory storage for transcripts
const transcripts = new Map();

app.use(express.json());

// Public transcript endpoints
app.get('/api/transcripts', (req, res) => {
  const transcriptList = Array.from(transcripts.values());
  res.json({ 
     transcripts: transcriptList,
     count: transcriptList.length,
     message: "Mercury transcript evidence/coverage system"
  });
});

app.get('/api/transcripts/:id', (req, res) => {
  const transcript = transcripts.get(req.params.id);
  if (!transcript) {
    return res.status(404).json({ error: 'Transcript not found' });
  }
  res.json(transcript);
});

app.post('/api/transcripts', (req, res) => {
  const { topic, content, contributorId } = req.body;
  
  // Validate required fields
  if (!topic || !content || !contributorId) {
    return res.status(400).json({ 
      error: 'Missing required fields: topic, content, contributorId' 
    });
  }
  
  // Create and validate transcript
  const newTranscript = createTranscript({ topic, content, contributorId });
  const validation = validateTranscriptSchema(newTranscript);
  
  if (!validation.valid) {
    return res.status(400).json({ 
      error: 'Validation failed',
      details: validation.errors 
    });
  }
  
  // Store transcript
  transcripts.set(newTranscript.id, newTranscript);
  
  res.status(201).json({ 
    success: true,
    transcript: newTranscript
  });
});

// Health check
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    service: 'peer-link',
    transcripts: transcripts.size,
    uptime: process.uptime()
  });
});

// Start server only when run directly
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Peer Link server running on port ${PORT}`);
    console.log(`Health check: http://localhost:${PORT}/health`);
    console.log(`Transcript API: http://localhost:${PORT}/api/transcripts`);
  });
}

module.exports = app;
