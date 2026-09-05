// Isolated fake-memory fixtures. Never opens or writes to a game process.
// Build CRT-free with /ENTRY:RemoteTestMain and kernel32.lib.
#include "skinchanger.cpp"

static int attrCalls = 0, updateCalls = 0, modelCalls = 0;
static void __fastcall FakeAttr(void*,const char*,float) { attrCalls++; }
static void __fastcall FakeUpdate(void* entity,bool) {
    updateCalls++;
    // Reproduce a material refresh resetting the visible mesh.
    uintptr_t node = *(uintptr_t*)((uintptr_t)entity+OFF_M_PGAMESCENENODE);
    if (node) *(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) = 0;
}
static void __fastcall FakeModel(void*,const char*) { modelCalls++; }
static void __fastcall FakeMask(void* node,uint64_t mesh) {
    *(uint64_t*)((uintptr_t)node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) = mesh;
}
static uintptr_t Allocate(SIZE_T size) {
    uintptr_t result = (uintptr_t)VirtualAlloc(0,size,MEM_COMMIT | MEM_RESERVE,PAGE_READWRITE);
    if (!result) ExitProcess(99);
    return result;
}
static void Check(int value, unsigned code) { if (!value) ExitProcess(code); }

extern "C" void RemoteTestMain() {
    uintptr_t client = Allocate(40*1024*1024), list = Allocate(4096), chunk = Allocate(512*0x70);
    uintptr_t local = Allocate(12000), localController = Allocate(4000);
    uintptr_t pawn = Allocate(12000), controller = Allocate(4000);
    uintptr_t weapon = Allocate(12000), ws = Allocate(4096), node = Allocate(4096);
    *(uintptr_t*)(client+OFF_DW_ENTITY_LIST) = list;
    *(uintptr_t*)(list+0x10) = chunk;
    *(uintptr_t*)(chunk+0x70*1) = localController;
    *(uintptr_t*)(chunk+0x70*64) = controller;
    *(uintptr_t*)(chunk+0x70*100) = pawn;
    *(uintptr_t*)(chunk+0x70*200) = weapon;
    *(uintptr_t*)(client+OFF_DW_GAMERULES) = 123456;
    *(uintptr_t*)(client+OFF_DW_LOCAL_PLAYER_PAWN) = local;
    *(uint32_t*)(local+R_CONTROLLER) = 1;
    *(uint64_t*)(localController+R_STEAMID) = 76561198864001604ULL;
    *(uint64_t*)(controller+R_STEAMID) = 76561198000000002ULL;
    *(uint32_t*)(controller+R_PLAYERPAWN) = 0x8064;
    *(uint32_t*)(pawn+R_CONTROLLER) = 64;
    *(int*)(pawn+R_HEALTH) = 100;
    *(uintptr_t*)(pawn+OFF_M_PWEAPONSERVICES) = ws;
    *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) = 0x80c8;
    *(uint32_t*)(weapon+R_OWNER) = 0x8064;
    *(uintptr_t*)(weapon+OFF_M_PGAMESCENENODE) = node;
    uintptr_t item = RemoteItem(weapon,0);
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 9;
    *(int*)(weapon+OFF_M_FALLBACKPAINTKIT) = 51;
    *(uint32_t*)(weapon+OFF_M_OWNERXUIDLOW) = 123;
    *(uint32_t*)(weapon+OFF_M_OWNERXUIDHIGH) = 456;
    g_setAttr = FakeAttr; g_updateSkin = FakeUpdate; g_setModel = FakeModel; g_setMask = FakeMask;
    g_remoteReadTick = GetTickCount64()+100000; // refresh immediately before each call below
    const char valid[] = "CS2PY_REMOTE_V1 1000 123456 76561198864001604 1\n76561198000000002 64 32868 32968 9 9 756 7 0.125 2 0 weapons/models/awp/weapon_snip_awp.vmdl\n";
    Check(RemoteParse(valid,valid+sizeof(valid)-1),1);
    RemoteEntry saved = g_remote[0];
    uintptr_t p, e;
    Check(RemoteResolve(client,&saved,&p,&e,1) && p == pawn && e == weapon,2);
    RemoteEntry bad = saved; bad.player++;
    Check(!RemoteResolve(client,&bad,&p,&e,1),3);
    bad = saved; bad.pawn += 0x8000;
    Check(!RemoteResolve(client,&bad,&p,&e,1),4);
    bad = saved; bad.handle += 0x8000;
    Check(!RemoteResolve(client,&bad,&p,&e,1),5);
    *(uint32_t*)(weapon+R_OWNER) = 1;
    Check(!RemoteResolve(client,&saved,&p,&e,1),6);
    *(uint32_t*)(weapon+R_OWNER) = 0x8064;
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 4;
    Check(!RemoteResolve(client,&saved,&p,&e,1),7);
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 9;
    *(int*)(pawn+R_HEALTH) = 0;
    Check(!RemoteResolve(client,&saved,&p,&e,1),8);
    *(int*)(pawn+R_HEALTH) = 100;
    g_remoteDeadline = remote_now_ms()+3000;
    g_remoteReadTick = GetTickCount64();
    ApplyRemoteSkins(client);
    Check(attrCalls == 3 && updateCalls == 1,9);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 756,10);
    Check(*(uint32_t*)(weapon+OFF_M_OWNERXUIDLOW) == 123 && *(uint32_t*)(weapon+OFF_M_OWNERXUIDHIGH) == 456,11);
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(attrCalls == 3 && updateCalls == 1,12); // unchanged: no expensive calls
    Check(*(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2,19);
    // A mesh-only reset is repaired without rebuilding all materials.
    *(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) = 1;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2 && updateCalls == 1,20);
    // Exactly two scheduled material follow-ups, then stop while unchanged.
    RemoteCache* cache = &g_remoteCache[126];
    cache->nextSettle = 0;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 2 && cache->settleRemaining == 1,21);
    cache->nextSettle = 0;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 3 && cache->settleRemaining == 0,22);
    cache->nextSettle = 0;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 3,23);
    // Recreated scene node triggers fresh material work and mesh restoration.
    uintptr_t replacementNode = Allocate(4096);
    *(uintptr_t*)(weapon+OFF_M_PGAMESCENENODE) = replacementNode;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 4 && *(uint64_t*)(replacementNode+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2,24);
    node = replacementNode;
    // AWP Printstream uses the new mesh; switching from a legacy paint must
    // finish on mesh 1 even when UpdateSkin clears it during rebuilding.
    g_remote[0].cfg.paint = 1206; g_remote[0].cfg.meshMask = 1;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 1206 &&
          *(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 1,25);
    int beforeGap = updateCalls;
    g_remoteCount = 0; g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 1206 && updateCalls == beforeGap,26);
    g_remoteCount = 1;
    *(uint8_t*)(node+259) = 1; // dormant keeps the baseline but performs no writes
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == beforeGap && cache->valid,27);
    *(uint8_t*)(node+259) = 0;
    int beforeExpiry = attrCalls;
    g_remoteDeadline = 0; g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 51 && attrCalls == beforeExpiry+3,13);
    // Default knife -> butterfly uses the world weapon model, then restores.
    uintptr_t originalModel = Allocate(4096);
    copy_str((char*)originalModel,"weapons/models/knife/knife_default_ct.vmdl",320);
    *(uintptr_t*)(node+OFF_M_MODELSTATE+168) = originalModel;
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 42;
    g_remote[0] = saved; g_remote[0].source = 42; g_remote[0].target = 515;
    copy_str(g_remote[0].cfg.model,"weapons/models/knife/knife_butterfly/weapon_knife_butterfly.vmdl",320);
    g_remoteDeadline = remote_now_ms()+3000; g_remoteReadTick = GetTickCount64();
    ApplyRemoteSkins(client);
    Check(*(uint16_t*)(item+OFF_M_ITEMDEFINDEX) == 515 && modelCalls == 1,17);
    g_remoteDeadline = 0; g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(uint16_t*)(item+OFF_M_ITEMDEFINDEX) == 42 && modelCalls == 2,18);
    // Gloves modify the pawn's inline item; never replace the whole pawn model.
    g_remote[0] = saved; g_remote[0].kind = 1; g_remote[0].handle = 0;
    g_remote[0].target = 5030; g_remote[0].cfg.paint = 10018;
    g_remoteDeadline = remote_now_ms()+3000; g_remoteReadTick = GetTickCount64();
    ApplyRemoteSkins(client);
    Check(*(uint16_t*)(pawn+R_GLOVES+OFF_M_ITEMDEFINDEX) == 5030,14);
    Check(*(uint8_t*)(pawn+R_REAPPLY_GLOVES) == 1 && modelCalls == 2,15);
    // Malformed/overflow input fails closed, clearing the render batch.
    const char badFile[] = "CS2PY_REMOTE_V1 18446744073709551616 0 0 0";
    Check(!RemoteParse(badFile,badFile+sizeof(badFile)-1) && g_remoteCount == 0,16);
    ExitProcess(0);
}
