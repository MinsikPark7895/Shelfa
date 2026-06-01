import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import '../styles/MyLibrary.css'
import ReservationModal from './ReservationModal'
import { apiFetch } from '../api'

interface BookData { id: string; title: string; author: string; cover_image_url: string; shelf_location: string; status: string }
interface LoanItem { id: string; book: BookData; due_date: string; borrowed_at: string; status: string }
interface FavItem { id: string; book: BookData; displayStatus: string }
interface ReservationItem { id: string; book: BookData; reserved_at: string; status: string }

function MyLibrary() {
  const [searchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'loans')
  const navigate = useNavigate()
  const [loanItems, setLoanItems] = useState<LoanItem[]>([])
  const [favoriteItems, setFavoriteItems] = useState<FavItem[]>([])
  const [storageItems, setStorageItems] = useState<ReservationItem[]>([])
  const [showExtensionModal, setShowExtensionModal] = useState(false)
  const [favBookIds, setFavBookIds] = useState<Set<string>>(new Set())
  const [isProcessing, setIsProcessing] = useState(false)
  const [selectedBook, setSelectedBook] = useState<BookData | null>(null)

  useEffect(() => { fetchLoans(); fetchFavorites(); fetchStorage() }, [activeTab])

  const fetchLoans = async () => {
    try {
      const res = await apiFetch('/loans/me?limit=50')
      if (res.ok) {
        const data = await res.json()
        setLoanItems(data.items || [])
      }
      // favBookIds 갱신
      const favRes = await apiFetch('/favorites/me?limit=100')
      if (favRes.ok) {
        const favData = await favRes.json()
        setFavBookIds(new Set(favData.items?.map((f: any) => f.book.id) || []))
      }
    } catch { /* */ }
  }

  const fetchFavorites = async () => {
    try {
      const [favRes, loanRes, resRes] = await Promise.all([
        apiFetch('/favorites/me?limit=100'),
        apiFetch('/loans/me?limit=50'),
        apiFetch('/reservations/me?limit=50'),
      ])
      const favData = favRes.ok ? await favRes.json() : { items: [] }
      const loanData = loanRes.ok ? await loanRes.json() : { items: [] }
      const resData = resRes.ok ? await resRes.json() : { items: [] }

      const myLoanIds = new Set(loanData.items?.map((l: any) => l.book.id) || [])
      const myResIds = new Set(resData.items?.filter((r: any) => r.status === 'pending').map((r: any) => r.book.id) || [])

      const items: FavItem[] = (favData.items || []).map((f: any) => {
        let displayStatus = 'available'
        if (myLoanIds.has(f.book.id)) displayStatus = 'my_loan'
        else if (myResIds.has(f.book.id)) displayStatus = 'my_reservation'
        else if (f.book.status !== 'available') displayStatus = 'borrowed'
        return { ...f, displayStatus }
      })
      setFavoriteItems(items)
      setFavBookIds(new Set(favData.items?.map((f: any) => f.book.id) || []))
    } catch { /* */ }
  }

  const fetchStorage = async () => {
    try {
      const res = await apiFetch('/reservations/me?limit=50')
      if (res.ok) {
        const data = await res.json()
        setStorageItems(data.items?.filter((r: any) => r.status === 'pending') || [])
      }
    } catch { /* */ }
  }

  const handleToggleFavorite = async (bookId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (isProcessing) return
    setIsProcessing(true)
    try {
      if (favBookIds.has(bookId)) {
        await apiFetch(`/favorites/${bookId}`, { method: 'DELETE' })
        setFavBookIds(prev => { const s = new Set(prev); s.delete(bookId); return s })
      } else {
        await apiFetch(`/favorites/${bookId}`, { method: 'POST' })
        setFavBookIds(prev => new Set(prev).add(bookId))
      }
    } catch { /* */ } finally { setIsProcessing(false) }
  }

  const handleReturn = async (loanId: string) => {
    if (isProcessing) return
    setIsProcessing(true)
    try {
      await apiFetch(`/loans/${loanId}/return`, { method: 'POST' })
      fetchLoans()
    } catch { alert('오류가 발생했습니다.') } finally { setIsProcessing(false) }
  }

  const getDday = (d: string) => { const diff = Math.ceil((new Date(d).getTime() - Date.now()) / 86400000); return `D-${Math.max(0, diff)}` }
  const formatDate = (d: string) => { const dt = new Date(d); return `${dt.getFullYear()}.${String(dt.getMonth() + 1).padStart(2, '0')}.${String(dt.getDate()).padStart(2, '0')}` }
  const getPickupDeadline = (d: string) => { const dt = new Date(d); dt.setHours(dt.getHours() + 1); return `${dt.getHours()}:${String(dt.getMinutes()).padStart(2, '0')}` }
  const isOverdue = (d: string) => Math.ceil((new Date(d).getTime() - Date.now()) / 86400000) <= 3

  return (
    <div className="page-container">
      <div className="top-nav"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg><span className="logo-text">XYZ 도서관</span></div>
      <div className="mylibrary-content">
        <h1 className="mylibrary-title">내 서재</h1>
        <div className="tab-group">
          <button className={`tab-btn ${activeTab === 'loans' ? 'active' : ''}`} onClick={() => setActiveTab('loans')}>대출현황</button>
          <button className={`tab-btn ${activeTab === 'favorites' ? 'active' : ''}`} onClick={() => setActiveTab('favorites')}>관심도서</button>
          <button className={`tab-btn ${activeTab === 'storage' ? 'active' : ''}`} onClick={() => setActiveTab('storage')}>보관도서</button>
        </div>

        {activeTab === 'loans' && (<div className="tab-content">
          <div className="section-count"><span className="section-count-title">총 {loanItems.length}권 대출 중</span></div>
          {loanItems.length === 0 ? <div className="tab-content-empty">대출한 책이 없습니다.</div> : (
            <div className="book-list">{loanItems.map(item => (<div className="book-card" key={item.id}>
              <div className="book-card-cover" onClick={() => navigate(`/book/${item.book.id}`)}>
                {item.book.cover_image_url ? <img src={item.book.cover_image_url} alt={item.book.title} /> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg>}
              </div>
              <div className="book-card-info">
                <div className="book-card-title-row"><div className="book-card-title">{item.book.title}</div>
                  <div className="book-card-actions">
                    <button className="book-card-fav-btn" onClick={(e) => handleToggleFavorite(item.book.id, e)}><svg viewBox="0 0 24 24" fill={favBookIds.has(item.book.id) ? '#E03131' : 'none'} stroke={favBookIds.has(item.book.id) ? '#E03131' : 'var(--gray-400)'} strokeWidth="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg></button>
                    <button className="book-card-return-btn" onClick={() => handleReturn(item.id)}>반납하기</button>
                  </div>
                </div>
                <div className="book-card-meta">{item.book.shelf_location}</div>
                <div className="book-card-meta">{item.book.author} 지음</div>
                <div className="book-card-due-row"><span className={`book-card-due ${isOverdue(item.due_date) ? 'overdue' : ''}`}>반납일: {formatDate(item.due_date)}</span><button className="book-card-extend-btn" onClick={() => setShowExtensionModal(true)}>연장하기</button></div>
              </div>
            </div>))}</div>
          )}
        </div>)}

        {activeTab === 'favorites' && (<div className="tab-content">
          <div className="section-count"><span className="section-count-title">총 {favoriteItems.length}권의 관심도서</span></div>
          {favoriteItems.length === 0 ? <div className="tab-content-empty">관심도서가 없습니다.</div> : (
            <div className="book-list">{favoriteItems.map(item => (<div className="book-card" key={item.id}>
              <div className="book-card-cover" onClick={() => navigate(`/book/${item.book.id}`)}>
                {item.book.cover_image_url ? <img src={item.book.cover_image_url} alt={item.book.title} /> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg>}
              </div>
              <div className="book-card-info">
                <div className="book-card-title-row"><div className="book-card-title">{item.book.title}</div>
                  <button className="book-card-fav-btn" onClick={(e) => handleToggleFavorite(item.book.id, e)}><svg viewBox="0 0 24 24" fill={favBookIds.has(item.book.id) ? '#E03131' : 'none'} stroke={favBookIds.has(item.book.id) ? '#E03131' : 'var(--gray-400)'} strokeWidth="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg></button>
                </div>
                <div className="book-card-meta">{item.book.shelf_location}</div>
                <div className="book-card-meta">{item.book.author} 지음</div>
                <div className="book-card-bottom-row">
                  {item.displayStatus === 'available' && (<><span className="badge-available">대출가능</span><button className="book-card-reserve-btn" onClick={() => setSelectedBook(item.book)}>예약하기</button></>)}
                  {(item.displayStatus === 'borrowed' || item.displayStatus === 'my_loan') && (<><span className="badge-unavailable">대출불가</span><button className="book-card-reserve-btn disabled" disabled>예약불가</button></>)}
                  {item.displayStatus === 'my_reservation' && (<><span className="badge-myreserve">예약완료</span><button className="book-card-reserve-btn disabled" disabled>예약완료</button></>)}
                </div>
              </div>
            </div>))}</div>
          )}
        </div>)}

        {activeTab === 'storage' && (<div className="tab-content">
          <div className="section-count"><span className="section-count-title">보관 중인 도서</span><span className="section-count-number">현재 {storageItems.length}권 보관중</span></div>
          {storageItems.length > 0 && (<div className="info-banner"><div className="info-banner-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></svg></div><span className="info-banner-text">수령 기한이 지나면 도서가 자동으로 반납됩니다.</span></div>)}
          {storageItems.length === 0 ? <div className="tab-content-empty">보관 중인 도서가 없습니다.</div> : (
            <div className="book-list">{storageItems.map(item => (<div className="book-card" key={item.id}>
              <div className="book-card-cover" onClick={() => navigate(`/book/${item.book.id}`)}>
                {item.book.cover_image_url ? <img src={item.book.cover_image_url} alt={item.book.title} /> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg>}
              </div>
              <div className="book-card-info">
                <div className="book-card-title-row"><div className="book-card-title">{item.book.title}</div>
                  <button className="book-card-fav-btn" onClick={(e) => handleToggleFavorite(item.book.id, e)}><svg viewBox="0 0 24 24" fill={favBookIds.has(item.book.id) ? '#E03131' : 'none'} stroke={favBookIds.has(item.book.id) ? '#E03131' : 'var(--gray-400)'} strokeWidth="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg></button>
                </div>
                <div className="book-card-meta">{item.book.shelf_location}</div>
                <div className="book-card-meta">{item.book.author} 지음</div>
                <div className="book-card-storage-badge"><span className="badge-storage">수령 대기</span></div>
                <div className="book-card-storage-info">
                  <div className="book-card-storage-row"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" /></svg><span>보관 장소: {item.book.shelf_location || '-'}</span></div>
                  <div className="book-card-storage-row deadline"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg><span>수령 기한: 금일 {getPickupDeadline(item.reserved_at)} 까지</span></div>
                </div>
              </div>
            </div>))}</div>
          )}
        </div>)}
      </div>

      {selectedBook && (
        <ReservationModal
          bookId={selectedBook.id}
          title={selectedBook.title}
          author={selectedBook.author}
          classNumber={selectedBook.shelf_location || ''}
          badgeLabel="대출가능"
          badgeClass="badge-available"
          onClose={() => setSelectedBook(null)}
          onSuccess={() => { setSelectedBook(null); fetchFavorites() }}
        />
      )}

      {showExtensionModal && (<div className="mypage-modal-overlay" onClick={() => setShowExtensionModal(false)}><div className="mypage-modal" onClick={(e) => e.stopPropagation()}><p className="mypage-modal-text">현재 지원하지 않는 기능입니다.</p><button className="mypage-modal-btn" onClick={() => setShowExtensionModal(false)}>확인</button></div></div>)}
      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item active" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내 서재</span></a>
        <a className="tab-item" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}
export default MyLibrary
