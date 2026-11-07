const dictionary = (map: Record<string, string>) => (value?: string | null) => (value ? map[value] ?? value : '')

export const statusLabel = dictionary({ active: 'Aktif', cancelled: 'İptal edildi', reversed: 'Ters kaydı yapıldı', archived: 'Arşivde' })

export const lifecycleLabel = dictionary({ planned: 'Planlandı', ordered: 'Sipariş verildi', partially_received: 'Kısmen teslim alındı', received: 'Teslim alındı' })

export const movementTypeLabel = dictionary({ accrual: 'Tahakkuk', opening_balance: 'Açılış bakiyesi', collection: 'Tahsilat', refund: 'İade', correction: 'Düzeltme', reversal: 'Ters kayıt' })

export const ledgerRowLabel = dictionary({ purchase_receipt: 'Teslim alınan alış', payment: 'Ödeme', payment_reversal: 'Ödeme ters kaydı', opening_balance: 'Açılış bakiyesi' })

export const eventStateLabel = dictionary({ overdue: 'Gecikmiş', today: 'Bugün', upcoming: 'Yaklaşan', completed: 'Tamamlandı', cancelled: 'İptal edildi' })

export const requestStateLabel = dictionary({ pending: 'Bekliyor', approved: 'Onaylandı', rejected: 'Reddedildi', cancelled: 'İptal edildi' })

export const workStatusLabel = dictionary({ worked: 'Çalıştı', absent: 'Gelmedi', half_day: 'Yarım gün', overtime: 'Fazla mesai', annual_leave: 'Yıllık izin', sick_leave: 'Hastalık izni', excused_leave: 'Mazeret izni', paid_leave: 'Ücretli izin', unpaid_leave: 'Ücretsiz izin', public_holiday: 'Resmî tatil', weekly_rest: 'Haftalık izin' })
