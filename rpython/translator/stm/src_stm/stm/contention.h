/* Imported by rpython/translator/stm/import_stmgc.py */

static void write_write_contention_management(uintptr_t lock_idx);
static void write_read_contention_management(uint8_t other_segment_num);
static void inevitable_contention_management(uint8_t other_segment_num);

static inline bool is_abort(uintptr_t nursery_end) {
    return (nursery_end <= _STM_NSE_SIGNAL_MAX && nursery_end != NSE_SIGPAUSE);
}

static inline bool is_aborting_now(uint8_t other_segment_num) {
    return (is_abort(get_segment(other_segment_num)->nursery_end) &&
            get_priv_segment(other_segment_num)->safe_point != SP_RUNNING);
}
