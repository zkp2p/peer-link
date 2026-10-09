use crate::models::{JobStatus, JobError, RecoveryMode};
use crate::storage::DurableState;
use crate::bank::ProviderError;

pub struct RecoveryManager {
    state: DurableState,
}

impl RecoveryManager {
    /// Implementação do Caso 1: Deferred Terminalization
    /// Se houver falha de provedor e falha de storage simultâneas, 
    /// marcamos para terminalização adiada para evitar replay de cobrança.
    pub async fn handle_critical_failure(&self, job_id: &str, error: JobError) -> Result<(), JobError> {
        match error {
            JobError::BankFailure(ProviderError::ConnectionTimeout) | 
            JobError::BankFailure(ProviderError::ServiceUnavailable) => {
                if self.state.is_storage_unreachable().await {
                    // Caso 1: Marcar para terminalização adiada (deferred terminalization)
                    // Não tentamos replay de requisições bancárias ou inferência faturada.
                    self.state.mark_for_deferred_terminalization(job_id).await?;
                    return Ok(());
                }
                Err(error)
            }
            _ => Err(error),
        }
    }

    /// Implementação do Caso 2: Paid Receipt Archival Recovery
    /// Garante que jobs restaurados via polling que ainda possuem trabalho de 
    /// arquivamento pendente disparem a recuperação do recibo.
    pub async fn reconcile_restored_job(&self, job_id: &str) -> Result<(), JobError> {
        let job = self.state.get_job(job_id).await?;
        
        if job.status == JobStatus::Paid && job.has_pending_archive_work() {
            // Trigger paid receipt archival recovery
            // Evita o erro de completar o registro de boot sem garantir o recibo.
            self.trigger_receipt_archival_recovery(job_id).await?;
        }
        
        Ok(())
    }

    async fn trigger_receipt_archival_recovery(&self, job_id: &str) -> Result<(), JobError> {
        // Lógica para garantir que o recibo seja arquivado sem nova chamada de pagamento
        self.state.ensure_receipt_integrity(job_id).await
    }
}
