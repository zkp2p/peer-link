#[derive(Debug, Clone, PartialEq)]
pub enum JobStatus {
    Pending,
    Running,
    Paid,
    Paused,
    Completed,
    DeferredTerminalization, // Novo status para o Caso 1
}

pub struct Job {
    pub id: String,
    pub status: JobStatus,
    pub has_archive_pending: bool,
    pub payment_nonce: u64,
    pub receipt_key: String,
}

impl Job {
    pub fn has_pending_archive_work(&self) -> bool {
        self.has_archive_pending
    }
}
