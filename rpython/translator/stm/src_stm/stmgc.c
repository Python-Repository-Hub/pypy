/* Imported by rpython/translator/stm/import_stmgc.py */
#define _GNU_SOURCE 1
#include "stmgc.h"
#include "stm/atomic.h"
#include "stm/list.h"
#include "stm/core.h"
#include "stm/pagecopy.h"
#include "stm/pages.h"
#include "stm/gcpage.h"
#include "stm/sync.h"
#include "stm/setup.h"
#include "stm/largemalloc.h"
#include "stm/nursery.h"
#include "stm/contention.h"
#include "stm/extra.h"
#include "stm/fprintcolor.h"
#include "stm/weakref.h"
#include "stm/marker.h"
#include "stm/finalizer.h"
#include "stm/hashtable.h"

#include "stm/misc.c"
#include "stm/list.c"
#include "stm/pagecopy.c"
#include "stm/pages.c"
#include "stm/prebuilt.c"
#include "stm/gcpage.c"
#include "stm/largemalloc.c"
#include "stm/nursery.c"
#include "stm/sync.c"
#include "stm/forksupport.c"
#include "stm/setup.c"
#include "stm/hash_id.c"
#include "stm/core.c"
#include "stm/contention.c"
#include "stm/extra.c"
#include "stm/fprintcolor.c"
#include "stm/weakref.c"
#include "stm/marker.c"
#include "stm/prof.c"
#include "stm/rewind_setjmp.c"
#include "stm/finalizer.c"
#include "stm/hashtable.c"
