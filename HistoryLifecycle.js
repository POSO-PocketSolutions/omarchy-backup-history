.pragma library

function shouldFinish(streamFinished, processExited, aborted, tearingDown) {
  return streamFinished && processExited && !aborted && !tearingDown
}
