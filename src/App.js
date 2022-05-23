import "./App.css";
import AceEditor from "react-ace";

import "ace-builds/src-noconflict/mode-yaml";
import "ace-builds/src-noconflict/theme-github";

function onChange(newValue) {
  console.log("change", newValue);
}

function App() {
  return (
    <AceEditor
      mode="yaml"
      theme="github"
      onChange={onChange}
      name="UNIQUE_ID_OF_DIV"
      editorProps={{ $blockScrolling: true }}
      setOptions={{
        enableBasicAutocompletion: true,
        enableLiveAutocompletion: true,
      }}
      value="test"
    />
  );
}

export default App;
