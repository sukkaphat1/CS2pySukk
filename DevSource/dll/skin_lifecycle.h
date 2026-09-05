// Short-lived Python permission plus independently sampled engine state.
// Included after skinshare_remote.h for the strict decimal/file-time helpers.
static const uintptr_t OFF_ENGINE_NETWORK = 9491632, OFF_ENGINE_SIGNON = 560;
struct RendererControl {
    uint64_t pid, deadline, local, shared, rules, list;
};
static RendererControl g_control = {};
static uintptr_t g_liveEngine = 0;
static char g_controlPath[MAX_PATH];

static int ControlParse(const char* s, const char* end, uint64_t pid, uint64_t now) {
    RendererControl next = {};
    g_localEnabled = g_shareEnabled = 0;
    memset(&g_control,0,sizeof(g_control));
    char magic[32];
    parse_token(&s,end,magic,sizeof(magic));
    if (!str_eq(magic,"CS2PY_CONTROL_V1") ||
        !parse_u64(&s,end,&next.pid) || !parse_u64(&s,end,&next.deadline) ||
        !parse_u64(&s,end,&next.local) || !parse_u64(&s,end,&next.shared) ||
        !parse_u64(&s,end,&next.rules) || !parse_u64(&s,end,&next.list)) return 0;
    skip_ws(&s,end);
    if (s != end || next.pid != pid || next.local > 1 || next.shared > 1 ||
        !next.deadline || next.deadline <= now || next.deadline > now+5000 ||
        next.rules < 0x10000 || next.list < 0x10000) return 0;
    g_control = next;
    g_localEnabled = (int)next.local; g_shareEnabled = (int)next.shared;
    return 1;
}

static void ReadControl() {
    g_localEnabled = g_shareEnabled = 0; // I/O failure is a stop, not stale permission
    if (!g_controlPath[0]) {
        char user[MAX_PATH];
        if (!GetEnvironmentVariableA("USERPROFILE",user,MAX_PATH)) return;
        build_path(g_controlPath,MAX_PATH,user,"cs2py_skin_control.txt");
    }
    HANDLE file = CreateFileA(g_controlPath,GENERIC_READ,
        FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,0,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,0);
    if (file == INVALID_HANDLE_VALUE) return;
    char data[256]; DWORD size = GetFileSize(file,0), copied = 0;
    int ok = size < sizeof(data) && ReadFile(file,data,size,&copied,0) && copied == size;
    CloseHandle(file);
    if (ok) ControlParse(data,data+copied,GetCurrentProcessId(),remote_now_ms());
}

static int RendererSessionCurrent(uintptr_t client) {
    uint64_t now = remote_now_ms();
    if ((!g_localEnabled && !g_shareEnabled) || g_control.pid != GetCurrentProcessId() ||
        now >= g_control.deadline || g_control.deadline > now+5000) return 0;
    uintptr_t rules = ReadRoot(client+OFF_DW_GAMERULES);
    uintptr_t list = ReadRoot(client+OFF_DW_ENTITY_LIST);
    uintptr_t pawn = ReadRoot(client+OFF_DW_LOCAL_PLAYER_PAWN);
    uintptr_t network = ReadRoot(g_liveEngine+OFF_ENGINE_NETWORK);
    int signon = 0;
    return rules && rules == g_control.rules && list && list == g_control.list &&
        pawn && network && ReadValue(network+OFF_ENGINE_SIGNON,&signon) && signon == 6;
}

static void ClearRendererCaches() {
    // Only our own bookkeeping. Never chase old entities to restore cosmetics.
    memset(g_remoteCache,0,sizeof(g_remoteCache));
    memset(g_localSkins,0,sizeof(g_localSkins));
    memset(g_bindings,0,sizeof(g_bindings));
    memset(g_remoteLastReject,0,sizeof(g_remoteLastReject));
    g_bindingRules = g_bindingList = 0;
    g_remoteCount = 0; g_remoteReadTick = 0;
}
