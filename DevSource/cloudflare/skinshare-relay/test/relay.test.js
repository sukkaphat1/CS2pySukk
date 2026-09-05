import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MatchRoom } from '../src/index.js';

const roomId = '0123456789abcdef';
const sockets = [];
function socket() {
  const ws = { attachment:{room_id:roomId}, messages:[], closed:false,
    deserializeAttachment() { return this.attachment; },
    serializeAttachment(a) { this.attachment = a; },
    send(data) { this.messages.push(JSON.parse(data)); },
    close() { this.closed = true; }
  };
  sockets.push(ws);
  return ws;
}
const env = { ROOM_TOKEN:'test-only-secret' };
function makeRoom() { return new MatchRoom({ getWebSockets:()=>sockets }, env); }
function send(room,ws,data) { return room.webSocketMessage(ws,JSON.stringify(data)); }
function hello(player) { return {type:'hello',protocol:1,match_id:roomId,player_id:player,map:'de_test',auth_token:env.ROOM_TOKEN}; }
function snapshot(player,sequence) {
  const gun = {item_key:'weapon_awp',category:'snipers',source_def:9,target_def:9,paint_kit:756,seed:0,wear:0.1,mesh_mask:1};
  return {type:'snapshot',protocol:1,match_id:roomId,sequence,state:{protocol:1,match_id:roomId,player_id:player,map:'de_test',session_number:1,roster:['1','2'],active_weapon:gun,loadout:[gun]}};
}
test('loadout delivery, unchanged refresh, restart, superseded sockets and hibernation',async()=>{
  const room = makeRoom(), a = socket(), b = socket();
  await send(room,a,hello('1')); await send(room,b,hello('2'));
  await send(room,a,snapshot('1',75));
  assert.equal(b.messages.at(-1).state.loadout[0].paint_kit,756);
  const before = b.messages.length;
  await send(room,a,snapshot('1',75));
  assert.equal(b.messages.length,before+1);
  const oldSession = b.messages.at(-1).relay_session;
  const restarted = socket();
  await send(room,restarted,hello('1'));
  await send(room,restarted,snapshot('1',1));
  assert.equal(b.messages.at(-1).sequence,1);
  assert.notEqual(b.messages.at(-1).relay_session,oldSession);
  const latest = b.messages.length;
  await send(room,a,snapshot('1',76));
  assert.equal(b.messages.length,latest);
  const awakened = makeRoom();
  await send(awakened,restarted,snapshot('1',2));
  assert.equal(b.messages.at(-1).sequence,2);
  assert.equal(b.messages.at(-1).type,'snapshot');
  const invalid = snapshot('1',3); invalid.state.loadout[0].wear = 99;
  await send(awakened,restarted,invalid);
  assert.equal(restarted.messages.at(-1).code,'invalid_snapshot');
});
