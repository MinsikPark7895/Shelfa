import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import '../styles/BookDetail.css'

// DB 연동 예정 - 책 상태 타입
type BookStatus = 'available' | 'borrowed' | 'my_loan' | 'my_reservation'
type ModalType = 'none' | 'confirm' | 'success' | 'fail'

interface BookData {
  id: string
  title: string
  author: string
  translator?: string
  publisher: string
  classNumber: string
  coverImage: string
  status: BookStatus
  availableCount: number
  synopsis: string
}

// DB 연동 예정 - 하드코딩 샘플
const sampleBook: BookData = {
  id: '1',
  title: 'METRO : 2033',
  author: '드미트리 글루코프스키',
  translator: '김하락',
  publisher: '제우미디어',
  classNumber: 'xxx.xx.x-STEAM(책번호)',
  coverImage: '',
  status: 'available',
  availableCount: 3,
  synopsis: '인류를 휩쓴 핵전쟁. 그리고 지하 세계의 시작.\n\n핵전쟁으로 지상이 파멸한 후, 살아남은 러시아 사람들은 모스크바 지하철로 숨어들었다. 그로부터 20년 뒤. 베데엔하역\'에서 평범한 나날을 보내던 청년 아르티옴 앞에 인간의 정신을 붕괴시키는 돌연변이, \'검은 존재\'가 나타나며 평화롭던 일상은 산산조각 난다.',
}

const STATUS_CONFIG = {
  available: {
    label: '대출가능',
    badgeClass: 'badge-available',
    buttonText: '예약하기',
    buttonDisabled: false,
  },
  borrowed: {
    label: '대출불가',
    badgeClass: 'badge-unavailable',
    buttonText: '예약불가',
    buttonDisabled: true,
  },
  my_loan: {
    label: '대출중',
    badgeClass: 'badge-myloan',
    buttonText: '이미 대출한 책입니다',
    buttonDisabled: true,
  },
  my_reservation: {
    label: '예약완료',
    badgeClass: 'badge-myreserve',
    buttonText: '이미 예약한 책입니다',
    buttonDisabled: true,
  },
}

function BookDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [isFavorite, setIsFavorite] = useState(false)
  const [modalType, setModalType] = useState<ModalType>('none')
  const [failReason, setFailReason] = useState('')

  // DB 연동 예정 - id로 책 데이터 조회
  const book = sampleBook
  const statusConfig = STATUS_CONFIG[book.status]

  // 대출 기한 계산 (당일 + 14일)
  const getDueDate = () => {
    const date = new Date()
    date.setDate(date.getDate() + 14)
    return `${date.getFullYear()}년 ${date.getMonth() + 1}월 ${date.getDate()}일`
  }

  const handleReservationClick = () => {
    if (statusConfig.buttonDisabled) return
    setModalType('confirm')
  }

  const handleReservationConfirm = () => {
    // TODO: DB 연동 - 예약 API 호출
    // 성공 시:
    setModalType('success')
    // 실패 시 (예시):
    // setFailReason('대출 한도를 초과했습니다.')
    // setModalType('fail')
  }

  const handleFavoriteToggle = () => {
    setIsFavorite(!isFavorite)
    // TODO: DB 연동 - 즐겨찾기 추가/삭제 API
  }

  return (
    <div className="page-container">
      {/* Top Nav */}
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          <path d="M8 7h6" /><path d="M8 11h4" />
        </svg>
        <span className="logo-text">XYZ 도서관</span>
      </div>

      <div className="bookdetail-content">
        {/* 헤더 */}
        <div className="bookdetail-header">
          <h1 className="bookdetail-title">도서상세</h1>
          <button className="bookdetail-favorite-btn" onClick={handleFavoriteToggle}>
            <svg viewBox="0 0 24 24" fill={isFavorite ? 'var(--navy)' : 'none'} stroke="var(--navy)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
            </svg>
          </button>
        </div>

        {/* 표지 이미지 */}
        <div className="bookdetail-cover-section">
          <div className="bookdetail-cover">
            {book.coverImage ? (
              <img src={book.coverImage} alt={book.title} className="bookdetail-cover-img" />
            ) : (
              <div className="bookdetail-cover-placeholder">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
                  <path d="M8 7h6" /><path d="M8 11h4" />
                </svg>
              </div>
            )}
          </div>
        </div>

        {/* 상태 뱃지 */}
        <div className="bookdetail-badge-row">
          <span className={`bookdetail-badge ${statusConfig.badgeClass}`}>{statusConfig.label}</span>
        </div>

        {/* 책 정보 */}
        <div className="bookdetail-info">
          <h2 className="bookdetail-book-title">{book.title}</h2>
          <p className="bookdetail-meta">
            {book.author} 저자
            {book.translator && <> {book.translator} 번역</>}
          </p>
          <p className="bookdetail-publisher">{book.publisher}</p>
          <p className="bookdetail-class-number">{book.classNumber}</p>
        </div>

        {/* 예약하기 버튼 */}
        <div className="bookdetail-action">
          <button
            className={`bookdetail-reserve-btn ${statusConfig.buttonDisabled ? 'disabled' : ''}`}
            onClick={handleReservationClick}
            disabled={statusConfig.buttonDisabled}
          >
            {statusConfig.buttonText}
          </button>
        </div>

        {/* 줄거리 */}
        <div className="bookdetail-synopsis">
          <h3 className="bookdetail-synopsis-title">줄거리</h3>
          <p className="bookdetail-synopsis-subtitle">{book.synopsis.split('\n')[0]}</p>
          <p className="bookdetail-synopsis-text">
            {book.synopsis.split('\n').slice(1).join('\n')}
          </p>
        </div>
      </div>

      {/* ===== 모달 ===== */}

      {/* 예약하기 확인 모달 */}
      {modalType === 'confirm' && (
        <div className="modal-overlay" onClick={() => setModalType('none')}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-book-info">
              <span className={`bookdetail-badge ${statusConfig.badgeClass}`}>{statusConfig.label}</span>
              <h3 className="modal-book-title">{book.title}</h3>
              <p className="modal-book-class">{book.classNumber}</p>
              <p className="modal-book-author">{book.author} 지음</p>
            </div>
            <div className="modal-loan-info">
              <p className="modal-loan-available">현재 {book.availableCount}권 대출 가능합니다.</p>
              <p className="modal-loan-due">• {getDueDate()}까지 대출 가능합니다.</p>
            </div>
            <button className="modal-reserve-btn" onClick={handleReservationConfirm}>예약하기</button>
          </div>
        </div>
      )}

      {/* 예약완료 모달 */}
      {modalType === 'success' && (
        <div className="modal-overlay">
          <div className="modal-content modal-result">
            <div className="modal-result-icon modal-success-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="#4CAF50" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <polyline points="9 12 11.5 14.5 16 9.5" />
              </svg>
            </div>
            <p className="modal-result-text">예약이 완료되었습니다.</p>
            <div className="modal-result-buttons">
              <button className="modal-btn-outline" onClick={() => { setModalType('none'); navigate('/search') }}>계속 예약하기</button>
              <button className="modal-btn-outline" onClick={() => navigate('/my-library')}>내 서재로</button>
            </div>
          </div>
        </div>
      )}

      {/* 예약실패 모달 */}
      {modalType === 'fail' && (
        <div className="modal-overlay">
          <div className="modal-content modal-result">
            <div className="modal-result-icon modal-fail-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="#E03131" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" />
                <line x1="9" y1="9" x2="15" y2="15" />
              </svg>
            </div>
            <p className="modal-result-text">예약에 실패하였습니다.</p>
            <p className="modal-fail-reason">{failReason}</p>
            <div className="modal-result-buttons">
              <button className="modal-btn-outline" onClick={() => { setModalType('none') }}>상세페이지로</button>
              <button className="modal-btn-outline" onClick={() => navigate('/my-library')}>내 서재로</button>
            </div>
          </div>
        </div>
      )}

      {/* Bottom Tab Bar */}
      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" />
          </svg>
          <span className="tab-label">홈</span>
        </a>
        <a className="tab-item" onClick={() => navigate('/my-library')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          </svg>
          <span className="tab-label">내 서재</span>
        </a>
        <a className="tab-item" onClick={() => navigate('/mypage')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
          </svg>
          <span className="tab-label">사용자</span>
        </a>
        <a className="tab-item active" onClick={() => navigate('/search')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <span className="tab-label">검색</span>
        </a>
        <a className="tab-item" onClick={() => navigate('/notifications')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
          <span className="tab-label">알림</span>
        </a>
      </div>
    </div>
  )
}

export default BookDetail
