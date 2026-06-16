import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../api'

interface ReservationModalProps {
  bookId: string
  title: string
  author: string
  classNumber: string
  badgeLabel: string
  badgeClass: string
  onClose: () => void
  onSuccess?: () => void
}

type ModalStep = 'confirm' | 'success' | 'fail'

function ReservationModal({ bookId, title, author, classNumber, badgeLabel, badgeClass, onClose, onSuccess }: ReservationModalProps) {
  const navigate = useNavigate()
  const [step, setStep] = useState<ModalStep>('confirm')
  const [failReason, setFailReason] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const getDueDate = () => {
    const date = new Date()
    date.setDate(date.getDate() + 14)
    return `${date.getFullYear()}년 ${date.getMonth() + 1}월 ${date.getDate()}일`
  }

  const handleConfirm = async () => {
    if (isLoading) return
    setIsLoading(true)
    try {
      const res = await apiFetch(`/reservations/${bookId}`, { method: 'POST' })

      if (res.ok) {
        setStep('success')
        if (onSuccess) onSuccess()
      } else {
        const err = await res.json().catch(() => ({}))
        setFailReason(err?.detail || '예약에 실패했습니다.')
        setStep('fail')
      }
    } catch {
      setFailReason('서버 연결에 실패했습니다.')
      setStep('fail')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={step === 'confirm' ? onClose : undefined}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close-btn" onClick={onClose}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        {step === 'confirm' && (
          <>
            <div className="modal-book-info">
              <span className={`bookdetail-badge ${badgeClass}`}>{badgeLabel}</span>
              <h3 className="modal-book-title">{title}</h3>
              <p className="modal-book-class">{classNumber}</p>
              <p className="modal-book-author">{author} 지음</p>
            </div>
            <div className="modal-loan-info">
              <p className="modal-loan-due">• {getDueDate()}까지 대출 가능합니다.</p>
            </div>
            <button className="modal-reserve-btn" onClick={handleConfirm} disabled={isLoading}>{isLoading ? '처리 중...' : '예약하기'}</button>
          </>
        )}

        {step === 'success' && (
          <div className="modal-result">
            <div className="modal-result-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="#4CAF50" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><polyline points="9 12 11.5 14.5 16 9.5" />
              </svg>
            </div>
            <p className="modal-result-text">예약이 완료되었습니다.</p>
            <p style={{ fontSize: '13px', color: '#666', margin: '4px 0 12px', textAlign: 'center' }}>🤖 로봇이 도서를 보관함으로 가져오는 중입니다.</p>
            <div className="modal-result-buttons">
              <button className="modal-btn-outline" onClick={() => { onClose(); navigate('/search') }}>계속 예약하기</button>
              <button className="modal-btn-outline" onClick={() => navigate('/my-library')}>내 서재로</button>
            </div>
          </div>
        )}

        {step === 'fail' && (
          <div className="modal-result">
            <div className="modal-result-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="#E03131" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
              </svg>
            </div>
            <p className="modal-result-text">예약에 실패하였습니다.</p>
            <p className="modal-fail-reason">{failReason}</p>
            <div className="modal-result-buttons">
              <button className="modal-btn-outline" onClick={onClose}>상세페이지로</button>
              <button className="modal-btn-outline" onClick={() => navigate('/my-library')}>내 서재로</button>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}

export default ReservationModal
