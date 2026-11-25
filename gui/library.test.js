import test from 'node:test';
import assert from 'node:assert/strict';
import {games,filterGames,artwork} from './library.js';
test('search ignores case and accents and combines category and letter filters',()=>{
 assert.equal(filterGames(games,'ELDEN')[0].id,1245620);
 assert.deepEqual(filterGames(games,'','Favoritos','S').map(g=>g.title),['Stardew Valley']);
 assert.equal(filterGames(games,'Hades','Rol').length,0);
 assert.equal(filterGames([{title:'Árbol',genre:'Aventura'}],'arbol').length,1);
 assert.equal(filterGames(games,'no such game').length,0);
 assert.equal(filterGames(games).length,12);
});
test('local games never request remote artwork',()=>assert.equal(artwork({local:true}),''));
import {safePath} from './dev.mjs';
import {resolve} from 'node:path';
test('preview server prevents encoded path traversal',()=>{
 assert.equal(safePath('/main.js'),resolve('main.js'));
 assert.equal(safePath('/..%2f..%2fetc/passwd'),null);
});
import {libraryLayout,centeredGames} from './library.js';
test('page capacity adapts to the window, keeping cards on screen',()=>{
 assert.deepEqual(libraryLayout(2560,1396),{columns:4,rows:2,pageSize:8,neighbors:5});
 assert.equal(libraryLayout(1280,720).pageSize,4);
 assert.equal(libraryLayout(390,844).pageSize,2);
 assert.equal(libraryLayout(390,1396).neighbors,1);
});
test('the focused strip wraps without scrolling or duplicate games',()=>{
 const items=[1,2,3,4,5,6].map(id=>({id}));
 assert.deepEqual(centeredGames(items,1,5).map(g=>g.id),[5,6,1,2,3]);
 assert.deepEqual(centeredGames(items,6,3).map(g=>g.id),[5,6,1]);
 assert.deepEqual(centeredGames(items,4,1).map(g=>g.id),[4]);
 assert.deepEqual(centeredGames([],1,5),[]);
 assert.equal(new Set(centeredGames(items.slice(0,2),1,5).map(g=>g.id)).size,2);
});
test('Sense anchors the selected game at the start and wraps the upcoming tiles',()=>{
 const items=[1,2,3,4,5].map(id=>({id}));
 assert.deepEqual(centeredGames(items,4,4,0).map(g=>g.id),[4,5,1,2]);
 assert.deepEqual(centeredGames(items,2,8,0).map(g=>g.id),[2,3,4,5,1]);
 assert.deepEqual(centeredGames([],2,8,0),[]);
});
